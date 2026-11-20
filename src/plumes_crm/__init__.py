import sys
from plumes_crm.sync import sync_gmail_messages

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "sync-gmail":
        print("Lancement de la synchronisation Gmail...")
        sync_gmail_messages()
    else:
        print("Usage : plumes-crm sync-gmail")

if __name__ == "__main__":
    main()
