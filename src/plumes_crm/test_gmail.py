import os

from plumes_crm.gmail_client import get_gmail_service


def main():
    service = get_gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    print("Connexion Gmail OK")
    print("Email connecté :", profile.get("emailAddress"))
    print("Nombre de messages :", profile.get("messagesTotal"))

    root = os.environ.get("GMAIL_LABEL", "Plumes Créatives")
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    selected = sorted(
        (l for l in labels if l["name"] == root or l["name"].startswith(root + "/")),
        key=lambda l: l["name"],
    )

    if not selected:
        print(f"\nAucun libellé '{root}' trouvé. Libellés disponibles :")
        for l in sorted(labels, key=lambda l: l["name"]):
            if l.get("type") == "user":
                print("  ", l["name"])
        return

    print(f"\nLibellés sous '{root}' :")
    for l in selected:
        info = service.users().labels().get(userId="me", id=l["id"]).execute()
        print(
            f"  {info['name']} : {info.get('threadsTotal', 0)} conversation(s), "
            f"{info.get('messagesTotal', 0)} message(s)"
        )


if __name__ == "__main__":
    main()
