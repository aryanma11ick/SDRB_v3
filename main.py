from src.agents.gmail_watcher import fetch_emails
import json

if __name__ == "__main__":
    emails = fetch_emails(limit=5)
    print(json.dumps(emails, indent=2))
