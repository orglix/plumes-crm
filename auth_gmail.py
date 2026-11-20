import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT = "http://localhost:8080/"

# autorise le retour sur http://localhost (rien ne transite sur le réseau)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

flow = InstalledAppFlow.from_client_secrets_file("secrets/credentials.json", SCOPES)
flow.redirect_uri = REDIRECT

auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

print("\n1) Envoie ce lien à ta femme, à ouvrir dans une fenêtre privée :\n")
print(auth_url)
print("\n2) Elle choisit son compte Gmail, clique sur « Paramètres avancés » puis")
print("   « Accéder à ... (non sécurisé) », puis autorise l'accès.")
print("3) La page finale affichera une erreur (« impossible de se connecter ») : c'est normal.")
print("   Elle copie l'adresse COMPLÈTE de cette page (http://localhost:8080/?state=...&code=...)\n")

redirected = input("Colle l'adresse ici : ").strip()
flow.fetch_token(authorization_response=redirected)

token_path = Path("secrets/token.json")
token_path.write_text(flow.credentials.to_json())
token_path.chmod(0o600)
print("\nToken écrit dans", token_path)
print("Refresh token présent :", bool(flow.credentials.refresh_token))
