import json, os
from plumes_crm.database import get_db_connection

DEFAULT_MSG_LIMIT = int(os.getenv("CRM_MSG_LIMIT", "15"))
DEFAULT_MSG_MAX_CHARS = int(os.getenv("CRM_MSG_MAX_CHARS", "0"))  # 0 = pas de troncature


def search_contacts(query: str, limit: int = 10) -> str:
  """Recherche des contacts par nom ou adresse e-mail."""
  pattern = f"%{query.strip()}%"
  sql = """
    SELECT id, email, name, created_at
    FROM contacts
    WHERE email ILIKE %s OR COALESCE(name, '') ILIKE %s
    ORDER BY id DESC
    LIMIT %s
  """
  with get_db_connection() as conn:
    with conn.cursor() as cur:
      cur.execute(sql, (pattern, pattern, limit))
      rows = cur.fetchall()
  return json.dumps(rows, default=str, ensure_ascii=False)


def get_contact_messages(
  contact_id: int | list[int],
  limit: int | None = None,
  max_chars: int | None = None,
) -> str:
  """Récupère les messages nettoyés d'un contact donné."""
  contact_ids = [contact_id] if isinstance(contact_id, int) else list(contact_id)
  effective_limit = limit if limit is not None else DEFAULT_MSG_LIMIT
  effective_max_chars = max_chars if max_chars is not None else DEFAULT_MSG_MAX_CHARS

  if effective_max_chars and effective_max_chars > 0:
    content_expr = "LEFT(COALESCE(cleaned_content, ''), %s) AS content"
    params: list[object] = [effective_max_chars, contact_ids]
  else:
    content_expr = "COALESCE(cleaned_content, '') AS content"
    params = [contact_ids]

  limit_clause = ""
  if effective_limit is not None and effective_limit > 0:
    limit_clause = "\n    LIMIT %s"
    params.append(effective_limit)

  sql = f"""
    SELECT id, thread_id, channel, direction, sender, subject, sent_at,
           {content_expr}
    FROM messages
    WHERE contact_id = ANY(%s)
    ORDER BY sent_at ASC NULLS LAST, id ASC{limit_clause}
  """
  with get_db_connection() as conn:
    with conn.cursor() as cur:
      cur.execute(sql, tuple(params))
      rows = cur.fetchall()
  return json.dumps(rows, default=str, ensure_ascii=False)


def list_inactive_contacts(min_days: int = 14, limit: int = 20) -> str:
  """Liste les contacts dont le dernier message date d'au moins min_days jours."""
  sql = """
    WITH last_msg AS (
      SELECT DISTINCT ON (contact_id)
        contact_id,
        direction,
        subject,
        sent_at,
        LEFT(COALESCE(cleaned_content, ''), 400) AS snippet
      FROM messages
      WHERE contact_id IS NOT NULL
      ORDER BY contact_id, sent_at DESC NULLS LAST, id DESC
    )
    SELECT c.id, c.email, c.name, lm.direction, lm.subject, lm.sent_at, lm.snippet
    FROM contacts c
    JOIN last_msg lm ON lm.contact_id = c.id
    WHERE lm.sent_at < NOW() - (%s || ' days')::interval
    ORDER BY lm.sent_at ASC
    LIMIT %s
  """
  with get_db_connection() as conn:
    with conn.cursor() as cur:
      cur.execute(sql, (min_days, limit))
      rows = cur.fetchall()
  return json.dumps(rows, default=str, ensure_ascii=False)
