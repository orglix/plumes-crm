import base64
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
import re
from typing import Any
import time
from typing import Callable, TypeVar
import os
from plumes_crm.database import DatabaseRepository
import logging
import json

logger = logging.getLogger("plumes_crm.assistant")

T = TypeVar("T")

from plumes_crm.database import get_db_connection

SYSTEM_FORM_EMAIL = "wordpress@plumes-creatives.fr"


def execute_with_quota_retry(
  request_builder: Callable[[], object],
  max_retries: int = 5,
  base_sleep: float = 20.0,
) -> T:
  """Exécute `request_builder().execute()` avec backoff sur erreurs de quota/réseau."""
  for attempt in range(max_retries + 1):
    try:
      req = request_builder()
      return req.execute()  # type: ignore[attr-defined, return-value]
    except Exception as exc:
      msg = str(exc).lower()
      is_quota = (
        "429" in msg
        or "ratelimitexceeded" in msg
        or "quota" in msg
        or "user rate limit exceeded" in msg
      )
      is_transient = (
        is_quota
        or "500" in msg
        or "502" in msg
        or "503" in msg
        or "504" in msg
        or "backenderror" in msg
        or "timed out" in msg
      )
      if not is_transient or attempt >= max_retries:
        raise
      sleep_s = base_sleep * (2**attempt)
      time.sleep(sleep_s)

  raise RuntimeError("Retries épuisés")


def getTargetLabel(service) -> set[str]:
  root_label = os.environ.get("GMAIL_LABEL", "Plumes Créatives")

  labels_res = execute_with_quota_retry(lambda: service.users().labels().list(userId="me")).get(
    "labels", []
  )

  target_label_ids = [
    l["id"] for l in labels_res if l["name"] == root_label or l["name"].startswith(root_label + "/")
  ]

  if not target_label_ids:
    raise ValueErrir(f"Aucun libellé trouvé pour '{root_label}'")
  return target_label_ids


def _extract_header(headers: list[dict[str, str]], name: str) -> str:
  target = name.lower()
  for h in headers:
    if (h.get("name") or "").lower() == target:
      return h.get("value") or ""
  return ""


def _decode_b64url(data: str | None) -> str:
  if not data:
    return ""
  padded = data + "=" * (-len(data) % 4)
  return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")


def _strip_html(raw_html: str) -> str:
  text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_html, flags=re.S | re.I)
  text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
  text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
  text = re.sub(r"<[^>]+>", " ", text)
  return re.sub(r"[ \t]+", " ", text).strip()


def _extract_plain_body(payload: dict[str, Any]) -> str:
  """Extrait le corps texte (priorité text/plain, repli sur text/html nettoyé)."""
  mime = (payload.get("mimeType") or "").lower()
  body_data = (payload.get("body") or {}).get("data")

  if mime == "text/plain" and body_data:
    return _decode_b64url(body_data).strip()

  html_fallback = ""
  for part in payload.get("parts") or []:
    part_mime = (part.get("mimeType") or "").lower()
    if part_mime == "text/plain":
      txt = _decode_b64url((part.get("body") or {}).get("data")).strip()
      if txt:
        return txt
    elif part_mime == "text/html" and not html_fallback:
      html_fallback = _strip_html(_decode_b64url((part.get("body") or {}).get("data")))
    elif part_mime.startswith("multipart/"):
      nested = _extract_plain_body(part)
      if nested:
        return nested

  if mime == "text/html" and body_data:
    return _strip_html(_decode_b64url(body_data))

  return html_fallback


def _clean_email_reply(text: str) -> str:
  """Supprime les citations historiques ('Le ... a écrit :') et espaces superflus."""
  lines: list[str] = []
  for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith(">"):
      continue
    if re.match(r"^Le\s.+a\s+écrit\s*:$", stripped):
      break
    if re.match(r"^On\s.+wrote:$", stripped):
      break
    lines.append(line)
  return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _resolve_contact_and_identity(
  cur,
  target_email: str,
  display_name: str | None,
) -> tuple[int, int]:
  """Retourne (contact_id, identity_id) depuis channels, ou crée le contact + channel."""
  email_norm = target_email.strip().lower()

  cur.execute(
    """
        SELECT id, contact_id
        FROM channels
        WHERE channel = 'gmail' AND identifier = %s
        """,
    (email_norm,),
  )
  existing = cur.fetchone()
  if existing:
    return existing["contact_id"], existing["id"]

  contact_name = (display_name or "").strip() or email_norm.split("@")[0]
  cur.execute(
    """
        INSERT INTO contacts (name, detected_status)
        VALUES (%s, 'active')
        RETURNING id
        """,
    (contact_name,),
  )
  contact_id = cur.fetchone()["id"]

  cur.execute(
    """
        INSERT INTO channels (contact_id, channel, identifier)
        VALUES (%s, 'gmail', %s)
        ON CONFLICT (channel, identifier) DO UPDATE
            SET contact_id = channels.contact_id
        RETURNING id
        """,
    (contact_id, email_norm),
  )
  identity_id = cur.fetchone()["id"]
  return contact_id, identity_id


def _get_label_id(service, label_name: str) -> str:
  resp = service.users().labels().list(userId="me").execute()
  for lbl in resp.get("labels", []):
    if lbl.get("name") == label_name:
      return lbl["id"]
  raise ValueError(f"Libellé Gmail introuvable : '{label_name}'")


def _list_label_message_ids(service, label_id: str) -> list[str]:
  ids: list[str] = []
  page_token: str | None = None
  while True:
    resp = (
      service.users()
      .messages()
      .list(
        userId="me",
        labelIds=[label_id],
        pageToken=page_token,
        maxResults=500,
      )
      .execute()
    )
    ids.extend(m["id"] for m in resp.get("messages", []))
    page_token = resp.get("nextPageToken")
    if not page_token:
      break
  return ids


from plumes_crm.gmail_client import get_gmail_service


def sync_gmail_messages() -> dict[str, Any]:
  """Synchronise les nouveaux messages Gmail d'un libellé vers PostgreSQL.
  Returns:
      Statistiques d'import et ensemble des contact_id mis à jour.
  """
  service = get_gmail_service()
  db = DatabaseRepository()
  target_label_ids = getTargetLabel(service)
  if not target_label_ids:
    return {"imported": 0, "skipped": 0, "updated_contact_ids": set()}

  print(f"Synchronisation pour {len(target_label_ids)} libellé(s).")
  profile = execute_with_quota_retry(lambda: service.users().getProfile(userId="me"))
  my_email = profile.get("emailAddress", "").lower()
  my_emails_norm = {my_email} if my_email else set()
  my_emails_norm.add("contact@plumes-creatives.fr")

  existing_ids = set(db.get_existing_gmail_ids())

  all_gmail_ids: list[str] = []
  seen_gmail_ids: set[str] = set()
  for label_id in target_label_ids:
    label_msg_ids = _list_label_message_ids(service, label_id)
    for mid in label_msg_ids:
      if mid not in seen_gmail_ids:
        seen_gmail_ids.add(mid)
        all_gmail_ids.append(mid)

  missing_ids = [mid for mid in all_gmail_ids if mid not in existing_ids]
  logger.info(
    f"{len(all_gmail_ids)} messages dans les libellés, {len(existing_ids)}"
    f" déjà en base -> {len(missing_ids)} nouveaux à importer."
  )
  total_missing = len(missing_ids)
  imported = 0
  updated_contact_ids: set[int] = set()
  return {
    "imported": imported,
    "skipped": len(existing_ids),
    "updated_contact_ids": updated_contact_ids,
  }

  # 2. Import de chaque nouveau message
  for mid in missing_ids:
    logger.info(f"Progression : {imported}/{total_missing} importés)")
    raw_msg = execute_with_quota_retry(
      lambda msg_id=mid: service.users().messages().get(userId="me", id=mid, format="full")
    )
    payload = raw_msg.get("payload") or {}
    headers = payload.get("headers") or []

    from_name, from_email = parseaddr(_extract_header(headers, "From"))
    to_name, to_email = parseaddr(_extract_header(headers, "To"))
    reply_name, reply_email = parseaddr(_extract_header(headers, "Reply-To"))
    subject = _extract_header(headers, "Subject").strip()
    date_header = _extract_header(headers, "Date")

    from_email = from_email.strip().lower()
    to_email = to_email.strip().lower()
    reply_email = reply_email.strip().lower()

    # Déterminer direction et interlocuteur cible
    if from_email in my_emails_norm:
      direction = "outbound"
      target_email = to_email
      target_name = to_name
    else:
      direction = "inbound"
      if from_email == SYSTEM_FORM_EMAIL and reply_email and reply_email != SYSTEM_FORM_EMAIL:
        target_email = reply_email
        target_name = from_name or reply_name
      else:
        target_email = from_email
        target_name = from_name

    if not target_email:
      continue

    try:
      sent_at = parsedate_to_datetime(date_header) if date_header else datetime.now(timezone.utc)
      if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    except Exception:
      sent_at = datetime.now(timezone.utc)

    raw_body = _extract_plain_body(payload)
    cleaned_content = _clean_email_reply(raw_body)

    with get_db_connection() as conn:
      with conn.cursor() as cur:
        contact_id, identity_id = _resolve_contact_and_identity(
          cur=cur,
          target_email=target_email,
          display_name=target_name,
        )
        thread_id = raw_msg.get("threadId")
        raw_payload_json = json.dumps(raw_msg, ensure_ascii=False)
        cur.execute(
          """
            INSERT INTO messages (
                contact_id,
                identity_id,
                external_id,
                thread_id,
                channel,
                sender,
                recipient,
                subject,
                raw_payload,
                cleaned_content,
                direction,
                sent_at
            )
            VALUES (%s, %s, %s, %s, 'gmail', %s, %s, %s, %s::jsonb, %s, %s, %s)
            ON CONFLICT (external_id) DO NOTHING
            RETURNING id
            """,
          (
            contact_id,
            identity_id,
            mid,
            thread_id,
            from_email or target_email,
            to_email or None,
            subject,
            raw_payload_json,
            cleaned_content,
            direction,
            sent_at,
          ),
        )
        if cur.fetchone():
          cur.execute(
            """
                        UPDATE contacts
                        SET last_interaction_at = GREATEST(
                            COALESCE(last_interaction_at, %s),
                            %s
                        )
                        WHERE id = %s
                        """,
            (sent_at, sent_at, contact_id),
          )
          imported += 1
          updated_contact_ids.add(contact_id)
      conn.commit()

  return {
    "imported": imported,
    "skipped": len(existing_ids),
    "updated_contact_ids": updated_contact_ids,
  }
