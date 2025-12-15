import json
from src.agents.gmail_watcher import fetch_emails
from src.agents.email_preprocessor import preprocess_email_llm
from src.agents.dispute_detector import detect_dispute

if __name__ == "__main__":
    emails = fetch_emails(limit=5)

    for email in emails:
        print("=" * 80)
        print("RAW EMAIL")
        print(json.dumps(email, indent=2))

        processed = preprocess_email_llm(email)
        print("\nPREPROCESSED")
        print(json.dumps(processed, indent=2))

        decision = detect_dispute(processed)
        print("\n DISPUTE DETECTION RESULT")
        print(json.dumps(decision, indent=2))

        print("=" * 80, "\n")
