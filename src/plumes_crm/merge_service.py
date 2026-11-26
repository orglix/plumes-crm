import re
from typing import Any
from plumes_crm.database import get_db_connection


SYSTEM_IDENTIFIERS: set[str] = {
    "wordpress@plumes-creatives.fr",
}


def _has_system_identifier(contact: dict[str, Any]) -> bool:
  for ch in contact.get("channels") or []:
    ident = (ch.get("identifier") or "").strip().lower()
    if ident in SYSTEM_IDENTIFIERS:
      return True
  return False


def _contact_has_system_channel(cur, contact_id: int) -> str | None:
  cur.execute(
      "SELECT identifier FROM channels WHERE contact_id = %s",
      (contact_id,),
  )
  for row in cur.fetchall():
    ident = (row["identifier"] or "").strip().lower()
    if ident in SYSTEM_IDENTIFIERS:
      return ident
  return None

def _name_signature(name: str | None) -> str:
  if not name:
    return ""
  tokens = sorted(re.findall(r"[a-zà-ÿ0-9]+", name.lower()))
  return " ".join(tokens)


def _identifier_prefix(identifier: str | None) -> str:
  if not identifier:
    return ""
  local = identifier.lower().strip().lstrip("@").split("@")[0]
  return re.sub(r"[._-]+", "", local)


def find_duplicate_candidates(limit: int = 30) -> list[dict[str, Any]]:
  """Détecte les paires de contacts susceptibles d'être la même personne."""
  sql_contacts = """
        SELECT
            c.id,
            c.name,
            c.last_interaction_at,
            COUNT(DISTINCT m.id) AS message_count,
            COALESCE(
                json_agg(
                    DISTINCT jsonb_build_object(
                        'id', ch.id,
                        'channel', ch.channel,
                        'identifier', ch.identifier
                    )
                ) FILTER (WHERE ch.id IS NOT NULL),
                '[]'::json
            ) AS channels
        FROM contacts c
        LEFT JOIN channels ch ON ch.contact_id = c.id
        LEFT JOIN messages m ON m.contact_id = c.id
        WHERE COALESCE(c.is_ignored, FALSE) = FALSE
        GROUP BY c.id
        ORDER BY c.last_interaction_at DESC NULLS LAST, c.id DESC
    """
  sql_ignored = (
      "SELECT contact_id_a, contact_id_b FROM ignored_duplicate_pairs"
  )

  with get_db_connection() as conn:
    with conn.cursor() as cur:
      cur.execute(sql_contacts)
      contacts = cur.fetchall()
      cur.execute(sql_ignored)
      ignored = {(r["contact_id_a"], r["contact_id_b"]) for r in cur.fetchall()}

  candidates: list[dict[str, Any]] = []
  seen_pairs: set[tuple[int, int]] = set()

  for i in range(len(contacts)):
    for j in range(i + 1, len(contacts)):
      a, b = contacts[i], contacts[j]
      if _has_system_identifier(a) or _has_system_identifier(b):
        continue
      pair_key = (min(a["id"], b["id"]), max(a["id"], b["id"]))
      if pair_key in ignored or pair_key in seen_pairs:
        continue

      reasons: list[str] = []
      sig_a, sig_b = _name_signature(a["name"]), _name_signature(b["name"])
      if sig_a and len(sig_a) >= 4 and sig_a == sig_b:
        reasons.append("Nom identique / inversé")

      prefixes_a = {
          _identifier_prefix(ch["identifier"]) for ch in a["channels"]
      } - {""}
      prefixes_b = {
          _identifier_prefix(ch["identifier"]) for ch in b["channels"]
      } - {""}
      common_prefixes = {p for p in (prefixes_a & prefixes_b) if len(p) >= 5}
      if common_prefixes:
        reasons.append(f"Identifiant proche ({', '.join(common_prefixes)})")

      if reasons:
        seen_pairs.add(pair_key)
        # Par défaut, celui avec le plus de messages devient le contact maître
        master, duplicate = (
            (a, b) if a["message_count"] >= b["message_count"] else (b, a)
        )
        candidates.append({
            "master": master,
            "duplicate": duplicate,
            "reasons": reasons,
        })
        if len(candidates) >= limit:
          return candidates

  return candidates


def merge_contacts(master_id: int, duplicate_id: int) -> dict[str, Any]:
  """Fusionne duplicate_id dans master_id dans une transaction atomique."""
  if master_id == duplicate_id:
    raise ValueError("Impossible de fusionner un contact avec lui-même.")

  with get_db_connection() as conn:
    with conn.cursor() as cur:
      sys_master = _contact_has_system_channel(cur, master_id)
      sys_dup = _contact_has_system_channel(cur, duplicate_id)
      if sys_master or sys_dup:
        blocked = sys_master or sys_dup
        raise ValueError(
            f"Fusion bloquée : l'adresse système '{blocked}' ne peut pas être"
            " fusionnée."
        )
      # 1. Rattacher les channels du doublon au maître
      cur.execute(
          "UPDATE channels SET contact_id = %s WHERE contact_id = %s",
          (master_id, duplicate_id),
      )

      # 2. Rattacher tous les messages au maître
      cur.execute(
          "UPDATE messages SET contact_id = %s WHERE contact_id = %s",
          (master_id, duplicate_id),
      )

     # 3. Nettoyer les paires ignorées obsolètes et recalculer last_interaction_at
      cur.execute(
          """
                DELETE FROM ignored_duplicate_pairs
                WHERE contact_id_a = %s OR contact_id_b = %s
                """,
          (duplicate_id, duplicate_id),
      )

      cur.execute(
          """
                UPDATE contacts
                SET last_interaction_at = (
                        SELECT MAX(sent_at) FROM messages WHERE contact_id = %s
                    )
                WHERE id = %s
                RETURNING id, name
                """,
          (master_id, master_id),
      )
      master = cur.fetchone()

      # 4. Supprimer la fiche doublon
      cur.execute("DELETE FROM contacts WHERE id = %s", (duplicate_id,))

    conn.commit()
  return {"merged_into": master, "deleted_id": duplicate_id}


def ignore_duplicate_pair(id_1: int, id_2: int) -> None:
  """Enregistre deux contacts comme distincts pour ne plus les proposer."""
  a, b = min(id_1, id_2), max(id_1, id_2)
  with get_db_connection() as conn:
    with conn.cursor() as cur:
      cur.execute(
          """
                INSERT INTO ignored_duplicate_pairs (contact_id_a, contact_id_b)
                VALUES (%s, %s)
                ON CONFLICT (contact_id_a, contact_id_b) DO NOTHING
                """,
          (a, b),
      )
    conn.commit()
