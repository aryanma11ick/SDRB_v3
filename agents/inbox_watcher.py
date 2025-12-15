import imaplib
import email
from email.header import decode_header
import os

from dotenv import load_dotenv
load_dotenv()

# Load and validate required environment variables
EMAIL_IMAP_SERVER = os.getenv("EMAIL_IMAP_SERVER")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

missing = [name for name, val in (("EMAIL_IMAP_SERVER", EMAIL_IMAP_SERVER), ("EMAIL_ADDRESS", EMAIL_ADDRESS), ("EMAIL_APP_PASSWORD", EMAIL_APP_PASSWORD)) if not val]
if missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def fetch_latest_emails(limit=10):
    imap = imaplib.IMAP4_SSL(EMAIL_IMAP_SERVER)
    imap.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)

    imap.select("INBOX")

    status, messages = imap.search(None, "ALL")
    email_ids = messages[0].split()[-limit:]

    emails = []

    for eid in email_ids:
        _, msg_data = imap.fetch(eid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        subject, encoding = decode_header(msg["Subject"])[0]
        subject = subject.decode(encoding or "utf-8") if isinstance(subject, bytes) else subject

        from_ = msg.get("From")

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")

        emails.append({
            "email_id": eid.decode(),
            "from": from_,
            "subject": subject,
            "body": body
        })

    imap.logout()
    return emails
