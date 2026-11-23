import os
import json
import psycopg
from psycopg.rows import dict_row


def get_db_connection():
  # Récupère l'URL de la base depuis l'environnement (défini dans docker-compose)
  db_url = os.environ.get(
    "DATABASE_URL", "postgresql://plumes_user:plumes_secret_password@localhost:5432/plumes_crm"
  )
  return psycopg.connect(db_url, row_factory=dict_row)


class DatabaseRepository:
  def __init__(self):
    pass

  def upsert_contact(self, email: str, name: str = None) -> int:
    """Crée ou met à jour un contact par son e-mail et retourne son ID."""
    if not email:
      return None

    with get_db_connection() as conn:
      with conn.cursor() as cur:
        # Cherche si le contact existe déjà
        cur.execute("SELECT id FROM contacts WHERE email = %s", (email,))
        row = cur.fetchone()

        if row:
          contact_id = row["id"]
          # Optionnel : mettre à jour le nom si fourni et absent
          if name and not row.get("name"):
            cur.execute("UPDATE contacts SET name = %s WHERE id = %s", (name, contact_id))
            conn.commit()
          return contact_id
        else:
          # Crée le contact
          cur.execute(
            "INSERT INTO contacts (email, name) VALUES (%s, %s) RETURNING id",
            (email, name or email.split("@")[0]),
          )
          contact_id = cur.fetchone()["id"]
          conn.commit()
          return contact_id

  def save_message(self, message_data: dict) -> bool:
    """
    Sauvegarde un message en base.
    Retourne True si inséré, False s'il existait déjà (grâce à external_id unique).
    """
    with get_db_connection() as conn:
      with conn.cursor() as cur:
        try:
          cur.execute(
            """
                        INSERT INTO messages (
                            contact_id, channel, external_id, thread_id,
                            sender, recipient, subject, raw_payload, direction, sent_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (external_id) DO NOTHING
                        RETURNING id;
                        """,
            (
              message_data.get("contact_id"),
              message_data.get("channel", "gmail"),
              message_data["external_id"],
              message_data.get("thread_id"),
              message_data["sender"],
              message_data.get("recipient"),
              message_data.get("subject"),
              json.dumps(message_data["raw_payload"]),
              message_data.get("direction", "inbound"),
              message_data.get("sent_at"),
            ),
          )
          inserted = cur.fetchone()
          conn.commit()
          return inserted is not None
        except Exception as e:
          conn.rollback()
          print(f"Erreur lors de l'insertion du message {message_data.get('external_id')}: {e}")
          return False

  def message_exists(self, external_id: str) -> bool:
    """Vérifie si un message existe déjà via son external_id."""
    with get_db_connection() as conn:
      with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM messages WHERE external_id = %s", (external_id,))
        return cur.fetchone() is not None

  def get_messages_to_clean(self, channel: str = "gmail", limit: int | None = None) -> list[dict]:
    """Récupère les messages dont cleaned_content est encore NULL."""
    query = """
      SELECT id, external_id, subject, raw_payload
      FROM messages
      WHERE channel = %s AND cleaned_content IS NULL
      ORDER BY id ASC
    """
    params: list = [channel]
    if limit is not None:
      query += " LIMIT %s"
      params.append(limit)

    with get_db_connection() as conn:
      with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()

  def update_cleaned_content(self, message_id: int, cleaned_content: str) -> None:
    """Met à jour cleaned_content pour un message donné."""
    with get_db_connection() as conn:
      with conn.cursor() as cur:
        cur.execute(
          "UPDATE messages SET cleaned_content = %s WHERE id = %s",
          (cleaned_content, message_id),
        )
        conn.commit()
