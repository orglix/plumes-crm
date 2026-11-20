import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
# TOKEN_PATH = Path(os.environ.get("GMAIL_TOKEN_PATH", "/app/secrets/token.json"))


def get_gmail_service():
    # Détermine le chemin du dossier secrets (soit dans /app/secrets, soit localement à la racine)
    # En local, on cherche dans ./secrets par rapport au répertoire courant ou au projet
    secrets_dir = Path(os.environ.get("SECRETS_DIR", "./secrets"))
    token_path = secrets_dir / "token.json"
    credentials_path = secrets_dir / "credentials.json"

    if not token_path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {token_path.absolute()}")

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        token_path.chmod(0o600)
    return build("gmail", "v1", credentials=creds)
