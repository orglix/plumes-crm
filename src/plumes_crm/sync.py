import os
import time
from email.utils import parseaddr, parsedate_to_datetime
from googleapiclient.errors import HttpError
from plumes_crm.gmail_client import get_gmail_service
from plumes_crm.database import DatabaseRepository

def parse_header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""

def execute_with_quota_retry(request_builder, max_retries=5, base_sleep=20):
    """Exécute une requête Google API en gérant le 429/403 rateLimitExceeded."""
    for attempt in range(max_retries):
        try:
            return request_builder().execute()
        except HttpError as e:
            is_quota = e.resp.status in (403, 429) and "quota" in str(e).lower()
            if not is_quota or attempt == max_retries - 1:
                raise
            wait_time = base_sleep * (2 ** attempt)
            print(f"Quota Gmail atteint (essai {attempt + 1}/{max_retries}). Pause de {wait_time}s...")
            time.sleep(wait_time)


def sync_gmail_messages():
    service = get_gmail_service()
    db = DatabaseRepository()

    root_label = os.environ.get("GMAIL_LABEL", "Plumes Créatives")

    labels_res = execute_with_quota_retry(
        lambda: service.users().labels().list(userId="me")
    ).get("labels", [])

    target_label_ids = [
        l["id"]
        for l in labels_res
        if l["name"] == root_label or l["name"].startswith(root_label + "/")
    ]

    if not target_label_ids:
        print(f"Aucun libellé trouvé pour '{root_label}'")
        return

    print(f"Synchronisation pour {len(target_label_ids)} libellé(s).")

    profile = execute_with_quota_retry(
        lambda: service.users().getProfile(userId="me")
    )
    my_email = profile.get("emailAddress", "").lower()

    total_synced = 0

    for label_id in target_label_ids:
        page_token = None
        while True:
            try:
                results = execute_with_quota_retry(
                    lambda pt=page_token: service.users().messages().list(
                        userId="me",
                        labelIds=[label_id],
                        pageToken=pt,
                    )
                )
            except HttpError as e:
                print(f"Erreur lors du listage ({label_id}) : {e}")
                break

            for msg_summary in results.get("messages", []):
                msg_id = msg_summary["id"]

                # Évite de consommer 5 unités API si déjà importé
                if db.message_exists(msg_id):
                    continue

                try:
                    msg_full = execute_with_quota_retry(
                        lambda mid=msg_id: service.users().messages().get(
                            userId="me",
                            id=mid,
                            format="full",
                        )
                    )
                except HttpError as e:
                    print(f"Échec pour le message {msg_id}: {e}")
                    continue

                payload = msg_full.get("payload", {})
                headers = payload.get("headers", [])

                subject = parse_header(headers, "Subject")
                sender_raw = parse_header(headers, "From")
                recipient_raw = parse_header(headers, "To")
                date_str = parse_header(headers, "Date")

                _, sender_email = parseaddr(sender_raw)
                _, recipient_email = parseaddr(recipient_raw)

                direction = "outbound" if sender_email.lower() == my_email else "inbound"
                contact_email = sender_email if direction == "inbound" else recipient_email
                contact_name = (
                    parseaddr(sender_raw)[0] if direction == "inbound" else parseaddr(recipient_raw)[0]
                )

                contact_id = db.upsert_contact(email=contact_email, name=contact_name)

                sent_at = None
                if date_str:
                    try:
                        sent_at = parsedate_to_datetime(date_str)
                    except Exception:
                        pass

                message_data = {
                    "channel": "gmail",
                    "external_id": msg_id,
                    "thread_id": msg_full.get("threadId"),
                    "sender": sender_email or sender_raw,
                    "recipient": recipient_email or recipient_raw,
                    "subject": subject,
                    "raw_payload": msg_full,
                    "direction": direction,
                    "sent_at": sent_at,
                    "contact_id": contact_id,
                }

                if db.save_message(message_data):
                    total_synced += 1
                    print(f"  [+] Message importé : {subject[:50]} ({msg_id})")

                time.sleep(0.4)

            page_token = results.get("nextPageToken")
            if not page_token:
                break            
            
    print(f"Synchronisation terminée. {total_synced} nouveaux messages ajoutés.")
