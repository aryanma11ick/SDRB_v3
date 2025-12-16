import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import base64

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
PROCESSED_LABEL_NAME = "Processed"
NON_DISPUTE_LABEL_NAME = "NonDispute"
DISPUTE_LABEL_NAME = "Dispute"


def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_or_create_label(service, label_name: str = PROCESSED_LABEL_NAME) -> str:
    """Return label ID for name, creating it if missing."""
    labels_response = service.users().labels().list(userId="me").execute()
    for label in labels_response.get("labels", []):
        if label.get("name") == label_name:
            return label.get("id")
    created = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return created["id"]


def mark_as_processed(service, message_id: str, label_id: str):
    """Apply the processed label to a message to avoid reprocessing."""
    mark_labels(service, message_id, [label_id])


def mark_labels(service, message_id: str, add_label_ids: list[str]):
    """Apply one or more labels to a Gmail message."""
    if not add_label_ids:
        return
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": add_label_ids, "removeLabelIds": []}
    ).execute()


def _decode_body(body: dict) -> str:
    """Decode a Gmail message body's base64 payload safely."""
    if not body:
        return ""
    data = body.get("data")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def _extract_body(payload: dict) -> str:
    """
    Extract text content from a Gmail message payload.
    Prefers text/plain; falls back to text/html if plain is absent.
    """
    if not payload:
        return ""

    # Some messages place content directly in payload.body
    direct_body = _decode_body(payload.get("body", {}))
    if direct_body:
        return direct_body

    plain_parts = []
    html_parts = []

    for part in payload.get("parts", []):
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            text = _decode_body(part.get("body", {}))
            if text:
                plain_parts.append(text)
        elif mime_type == "text/html":
            text = _decode_body(part.get("body", {}))
            if text:
                html_parts.append(text)
        else:
            # Nested multipart/alternative; recurse
            nested = _extract_body(part)
            if nested:
                plain_parts.append(nested)

    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        return "\n".join(html_parts)
    return ""


def fetch_emails(
    limit=5,
    exclude_processed: bool = True,
    processed_label: str = PROCESSED_LABEL_NAME
):
    service = get_gmail_service()
    query = None
    if exclude_processed:
        # Gmail search skips messages with the processed label
        query = f"-label:{processed_label}"

    results = service.users().messages().list(
        userId="me", maxResults=limit, q=query
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()

        headers = msg_data["payload"]["headers"]
        subject = from_ = date = ""
        message_id_header = None

        for h in headers:
            name = h["name"]
            if name == "Subject":
                subject = h["value"]
            if name == "From":
                from_ = h["value"]
            if name == "Date":
                date = h["value"]
            # Gmail returns "Message-ID" header we need for threading
            if name.lower() == "message-id":
                message_id_header = h["value"]

        body = _extract_body(msg_data.get("payload", {}))

        emails.append({
            "email_id": msg["id"],
            "thread_id": msg["threadId"],
            "from": from_,
            "subject": subject,
            "date": date,
            "body": body,
            # The RFC Message-ID header (not the Gmail message resource id)
            "message_id_header": message_id_header,
        })

    return emails
