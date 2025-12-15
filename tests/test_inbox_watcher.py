from src.agents.inbox_watcher import InboxWatcherAgent
import json

if __name__ == "__main__":
    watcher = InboxWatcherAgent()
    emails = watcher.fetch_emails()

    print(json.dumps(emails, indent=2))
