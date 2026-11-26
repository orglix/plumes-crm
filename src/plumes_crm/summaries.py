from collections import defaultdict
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from plumes_crm.database import get_db_connection
from plumes_crm.crm_tools import get_contact_messages

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES: tuple[str, ...] = (
  "coaching",
  "beta-lecture",
  "ateliers",
  "autres",
)

prompt_file = Path("config/system_prompt.txt")
if prompt_file.exists():
  BASE_SUMMARY_PROMPT = prompt_file.read_text(encoding="utf-8").strip()
else:
  raise ValueError("No System Prompt found")

DEFAULT_MODEL = os.getenv("CRM_LLM_MODEL", "")
FALLBACK_MODELS = []


# Fonction attendue : prend le prompt final (str) et retourne la réponse brute du LLM (str).
LlmCompleteFn = Callable[[str], str]

# Fonction attendue : prend (contact_id: int, limit: int | None) et retourne une liste de dicts
# représentant les messages nettoyés du contact (sans pièces jointes).
FetchContactMessagesFn = Callable[[int, int | None], list[dict[str, Any]]]


import litellm
import time
import re
from litellm.exceptions import RateLimitError


def _extract_retry_after_seconds(exc: Exception, default: float = 35.0) -> float:
  match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", str(exc), re.IGNORECASE)
  if match:
    return float(match.group(1)) + 2.0
  return default


def complete_summary_prompt(prompt: str, max_rate_limit_retries: int = 2) -> str:
  for attempt in range(max_rate_limit_retries + 1):
    try:
      response = litellm.completion(
        model=DEFAULT_MODEL,
        fallbacks=[],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        timeout=60,
        num_retries=0,
      )
      return response.choices[0].message.content or ""
    except RateLimitError as exc:
      if attempt >= max_rate_limit_retries:
        raise
      wait_sec = _extract_retry_after_seconds(exc)
      logger.warning(
        "Rate limit Groq atteint (TPM). Pause de %.1fs avant nouvelle tentative (%d/%d)...",
        wait_sec,
        attempt + 1,
        max_rate_limit_retries,
      )
      time.sleep(wait_sec)
  return ""


def _make_thread_key(msg: dict[str, Any]) -> str:
  raw_thread = msg.get("thread_id")
  if raw_thread and str(raw_thread).strip():
    return str(raw_thread).strip()
  # Repli déterministe si thread_id est NULL pour éviter d'écraser des échanges distincts
  fallback_id = msg.get("id") or msg.get("external_id") or "unknown"
  return f"unthreaded:{fallback_id}"


def _extract_clean_text(msg: dict[str, Any]) -> str:
  raw = msg.get("content")
  if raw is None:
    raw = msg.get("cleaned_content")
  if not isinstance(raw, str):
    return ""
  return raw.strip()


def _parse_sent_at(value: Any) -> datetime | None:
  if value is None:
    return None
  if isinstance(value, datetime):
    return value
  if isinstance(value, str):
    try:
      return datetime.fromisoformat(value)
    except ValueError:
      return None
  return None


def _compute_thread_digest(messages: list[dict[str, Any]]) -> str:
  hasher = hashlib.sha256()
  for msg in messages:
    msg_id = str(msg.get("id") or msg.get("external_id") or "")
    sent_at = str(msg.get("sent_at") or "")
    direction = str(msg.get("direction") or "")
    sender = str(msg.get("sender") or "")
    subject = str(msg.get("subject") or "")
    text = _extract_clean_text(msg)
    hasher.update(f"{msg_id}|{sent_at}|{direction}|{sender}|{subject}|{text}".encode("utf-8"))
  return hasher.hexdigest()


def _build_transcript(contact_id: int, thread_key: str, messages: list[dict[str, Any]]) -> str:
  lines: list[str] = [
    f"Contact ID : {contact_id}",
    f"Thread : {thread_key}",
    "--- Début de l'échange ---",
  ]
  for msg in messages:
    dt = _parse_sent_at(msg.get("sent_at"))
    ts = (
      dt.isoformat() if dt else (str(msg.get("sent_at")) if msg.get("sent_at") else "date inconnue")
    )
    channel = msg.get("channel") or "canal inconnu"
    direction = msg.get("direction") or "direction inconnue"
    sender = msg.get("sender") or "expéditeur inconnu"
    subject = f" | Objet : {msg['subject']}" if msg.get("subject") else ""
    body = _extract_clean_text(msg)
    lines.append(f"[{ts}] ({channel} / {direction}{subject}) {sender} :\n{body}")
  lines.append("--- Fin de l'échange ---")
  return "\n\n".join(lines)


def _build_prompt(transcript: str, base_prompt: str = BASE_SUMMARY_PROMPT) -> str:
  allowed_str = ", ".join(ALLOWED_CATEGORIES)
  return (
    f"{base_prompt}\n\n"
    f"Classe également cet échange dans une ou plusieurs catégories parmi : [{allowed_str}]. "
    "Un échange peut appartenir à plusieurs catégories si pertinent. "
    "Utilise 'autres' uniquement si aucune autre catégorie ne convient.\n\n"
    "N'utilise aucun tool externe.\n\n"
    "Réponds UNIQUEMENT avec un objet JSON valide de la forme exacte :\n"
    '{"summary": "texte du résumé", "categories": ["categorie1", "categorie2"]}\n\n'
    f"{transcript}"
  )


def _parse_llm_response_with_meta(raw_response: str) -> tuple[str, list[str], bool]:
  cleaned = raw_response.strip()
  # Retire d'éventuelles balises ```json ... ``` si le modèle en ajoute
  if cleaned.startswith("```"):
    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
      lines = lines[1:]
    if lines and lines[-1].strip() == "```":
      lines = lines[:-1]
    cleaned = "\n".join(lines).strip()

  try:
    payload = json.loads(cleaned)
  except json.JSONDecodeError:
    # Repli : texte brut considéré comme résumé, catégorie par défaut 'autres'
    return cleaned, ["autres"], True

  if not isinstance(payload, dict):
    return cleaned, ["autres"], True

  summary = str(payload.get("summary") or "").strip()
  if not summary:
    return "", ["autres"], True

  raw_cats = payload.get("categories")
  categories: list[str] = []
  used_fallback = False

  if isinstance(raw_cats, list):
    for cat in raw_cats:
      if not isinstance(cat, str):
        continue
      normalized = cat.strip().lower()
      if normalized in ALLOWED_CATEGORIES and normalized not in categories:
        categories.append(normalized)
  else:
    used_fallback = True

  if not categories:
    categories = ["autres"]
    used_fallback = True

  return summary, categories, used_fallback


def _get_target_contact_ids(cur: Any, contact_ids: list[int] | None = None) -> list[int]:
  if contact_ids is not None:
    return [int(cid) for cid in contact_ids]

  cur.execute(
    """
      SELECT id
      FROM contacts
      WHERE COALESCE(is_ignored, false) = false
      ORDER BY id ASC
      """
  )
  return [row["id"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]


from dataclasses import dataclass
import time


@dataclass
class SummaryRunStats:
  contacts_processed: int = 0
  threads_found: int = 0
  threads_skipped_unchanged: int = 0
  threads_updated: int = 0
  threads_failed: int = 0


def generate_thread_summaries(
  complete_llm: LlmCompleteFn = complete_summary_prompt,
  fetch_messages: FetchContactMessagesFn = get_contact_messages,
  contact_ids: list[int] | None = None,
  messages_limit_per_contact: int | None = None,
  min_interval_sec: int = 2,
  base_prompt: str = BASE_SUMMARY_PROMPT,
  force: bool = False,
) -> int:
  """Génère et met à jour les résumés et catégories par thread dans `thread_summaries`."""
  last_llm_call_at = None
  with get_db_connection() as conn:
    with conn.cursor() as cur:
      target_contacts = _get_target_contact_ids(cur, contact_ids=contact_ids)
      logger.info("Traitement des résumés pour %d contact(s)...", len(target_contacts))

      for contact_id in target_contacts:
        SummaryRunStats.contacts_processed += 1
        raw_messages = fetch_messages(contact_id, messages_limit_per_contact)
        if not raw_messages:
          continue

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for msg in raw_messages:
          if not _extract_clean_text(msg):
            continue
          t_key = _make_thread_key(msg)
          grouped[t_key].append(msg)

        for thread_key, thread_msgs in grouped.items():
          thread_msgs.sort(
            key=lambda m: (
              _parse_sent_at(m.get("sent_at")) or datetime.max,
              int(m.get("id") or 0),
            )
          )
          SummaryRunStats.threads_found += 1
          digest = _compute_thread_digest(thread_msgs)

          cur.execute(
            """
              SELECT source_digest
              FROM thread_summaries
              WHERE contact_id = %s AND thread_key = %s
              """,
            (contact_id, thread_key),
          )
          existing = cur.fetchone()
          existing_digest = (
            (existing["source_digest"] if isinstance(existing, dict) else existing[0])
            if existing
            else None
          )

          if not force and existing_digest == digest:
            SummaryRunStats.threads_skipped_unchanged += 1
            continue

          last_dt = None
          for m in reversed(thread_msgs):
            parsed = _parse_sent_at(m.get("sent_at"))
            if parsed is not None:
              last_dt = parsed
              break

          transcript = _build_transcript(contact_id, thread_key, thread_msgs)
          prompt = _build_prompt(transcript, base_prompt=base_prompt)

          # Exemple de pacing simple avant chaque appel LLM réellement effectué :
          if min_interval_sec > 0 and last_llm_call_at is not None:
            elapsed = time.monotonic() - last_llm_call_at
            if elapsed < min_interval_sec:
              time.sleep(min_interval_sec - elapsed)

          last_llm_call_at = time.monotonic()
          try:
            raw_llm_out = complete_llm(prompt)
          except Exception as exc:
            logger.error(
              "Échec appel LLM pour contact_id=%s thread_key=%s (%d msg(s)) : %s — sera retenté au prochain passage.",
              contact_id,
              thread_key,
              len(thread_msgs),
              exc,
            )
            SummaryRunStats.threads_failed += 1
            continue

          if not raw_llm_out or not raw_llm_out.strip():
            logger.warning(
              "Réponse LLM vide pour contact_id=%s thread_key=%s (%d msg(s)) — ignoré, sera retenté.",
              contact_id,
              thread_key,
              len(thread_msgs),
            )
            SummaryRunStats.threads_failed += 1
            continue

          summary, categories, used_fallback = _parse_llm_response_with_meta(raw_llm_out)
          if not summary:
            logger.warning(
              "Résumé vide après parsing pour contact_id=%s thread_key=%s — ignoré, sera retenté. Extrait brut : %r",
              contact_id,
              thread_key,
              raw_llm_out[:200],
            )
            SummaryRunStats.threads_failed += 1
            continue

          if used_fallback:
            logger.warning(
              "Parsing JSON en repli pour contact_id=%s thread_key=%s -> catégories=%s",
              contact_id,
              thread_key,
              categories,
            )

          cur.execute(
            """
              INSERT INTO thread_summaries (
                  contact_id,
                  thread_key,
                  summary,
                  categories,
                  source_digest,
                  message_count,
                  last_message_at,
                  created_at,
                  updated_at
              )
              VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
              ON CONFLICT (contact_id, thread_key) DO UPDATE SET
                  summary = EXCLUDED.summary,
                  categories = EXCLUDED.categories,
                  source_digest = EXCLUDED.source_digest,
                  message_count = EXCLUDED.message_count,
                  last_message_at = EXCLUDED.last_message_at,
                  updated_at = CURRENT_TIMESTAMP
              """,
            (
              contact_id,
              thread_key,
              summary,
              categories,
              digest,
              len(thread_msgs),
              last_dt,
            ),
          )
          if cur.rowcount != 1:
            logger.warning(
              "UPSERT inattendu (rowcount=%s) pour contact_id=%s thread_key=%s",
              cur.rowcount,
              contact_id,
              thread_key,
            )
            SummaryRunStats.threads_failed += 1
            continue

          SummaryRunStats.threads_updated += 1
          logger.info(
            "Résumé enregistré : contact_id=%s thread_key=%s categories=%s msgs=%d",
            contact_id,
            thread_key,
            categories,
            len(thread_msgs),
          )
    conn.commit()

  #  logger.info("Génération terminée : %d résumé(s) de thread enregistré(s).", updated_count)
  return SummaryRunStats
