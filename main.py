<<<<<<< HEAD
import json
from src.agents.gmail_watcher import fetch_emails
from src.agents.email_preprocessor import preprocess_email_llm

if __name__ == "__main__":
    print("📥 Fetching emails from Gmail...\n")

    emails = fetch_emails(limit=5)

    print(f"✅ Fetched {len(emails)} email(s)\n")

    for idx, email in enumerate(emails, start=1):
        print("=" * 80)
        print(f"📧 EMAIL {idx} — RAW")
        print(json.dumps(email, indent=2))

        print("\n🤖 Running LLM Email Preprocessor...\n")

        processed = preprocess_email_llm(email)

        print("🧹 PREPROCESSED OUTPUT")
        print(json.dumps(processed, indent=2))
        print("=" * 80, "\n")
=======
from src.agents.gmail_watcher import fetch_emails
import json

if __name__ == "__main__":
    emails = fetch_emails(limit=5)
    print(json.dumps(emails, indent=2))
>>>>>>> b760854710fc32e50d6f0a74d9fcbf18039b8150
