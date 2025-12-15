<<<<<<< HEAD
import json
from src.agents.email_preprocessor import preprocess_email_llm

# Sample email (your exact example)
sample_email = {
    "email_id": "19b21675651dd565",
    "from": "Google <no-reply@accounts.google.com>",
    "subject": "Your Google Account was recovered successfully",
    "date": "Mon, 15 Dec 2025 09:46:15 GMT",
    "body": (
        "[image: Google]\n"
        "Account recovered successfully\n\n"
        "temp.mail.11042005@gmail.com\n"
        "Welcome back to your account\n"
        "You received this email to let you know about important changes "
        "to your Google Account and services.\n"
        "© 2025 Google LLC, 1600 Amphitheatre Parkway, Mountain View, CA 94043, USA"
    )
}

if __name__ == "__main__":
    print("🔹 Raw email input:")
    print(json.dumps(sample_email, indent=2))

    print("\n🔹 Running LLM preprocessor...\n")

    processed = preprocess_email_llm(sample_email)

    print("✅ Preprocessed output:")
    print(json.dumps(processed, indent=2))
=======
import imaplib
>>>>>>> b760854710fc32e50d6f0a74d9fcbf18039b8150
