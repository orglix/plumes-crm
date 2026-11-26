import sys, logging
from plumes_crm.sync import sync_gmail_messages #, clean_existing_messages
from plumes_crm.assistant import run_chat_turn


def run_cli_chat() -> None:
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
  )
  logging.getLogger("LiteLLM").setLevel(logging.WARNING)
  logging.getLogger("httpx").setLevel(logging.WARNING)
  history: list[dict] = []
  print("Assistant Plumes Créatives (tape 'exit' ou 'quit' pour quitter)\n")

  while True:
    try:
      user_input = input("Toi > ").strip()
    except EOFError, KeyboardInterrupt:
      print("\nÀ bientôt.")
      break

    if not user_input:
      continue
    if user_input.lower() in {"exit", "quit", "q"}:
      print("À bientôt.")
      break

    try:
      reply, history = run_chat_turn(history, user_input)
      print(f"\nIA > {reply}\n")
    except Exception as exc:
      print(f"\n[Erreur] {exc}\n")


def main():
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
      force=True,
  )
  if len(sys.argv) > 1 and sys.argv[1] == "sync-gmail":
    print("Lancement de la synchronisation Gmail...")
    sync_gmail_messages()
  # elif len(sys.argv) > 1 and sys.argv[1] == "clean-messages":
  #   limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
  #   print(f"Nettoyage de {limit} message(s) en attente...")
  #   clean_existing_messages(limit=limit)
  elif len(sys.argv) > 1 and sys.argv[1] == "chat":
    run_cli_chat()
  elif len(sys.argv) > 1 and sys.argv[1] == "serve":
    import uvicorn

    host = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 8000
    uvicorn.run("plumes_crm.web:app", host=host, port=port, reload=True, reload_dirs=["src"])
  else:
    print("Usage : plumes-crm sync-gmail")


if __name__ == "__main__":
  main()
