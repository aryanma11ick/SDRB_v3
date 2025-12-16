import base64
from email.message import EmailMessage
from datetime import datetime, timezone

from src.agents.stm_manager import STMManager
from src.agents.gmail_watcher import get_gmail_service


class ClarificationMailerAgent:
    """
    Sends clarification questions as replies in the same Gmail thread.
    """

    def __init__(self):
        self.stm_manager = STMManager()
        self.gmail_service = get_gmail_service()

    def send_clarification(
        self,
        thread_id: str,
        original_email_id: str,
        supplier_email_id: str,
        original_subject: str,
        clarification_question: str,
        sender_display_name: str = "Accounts Payable Team"
    ) -> dict:
        """
        Sends the clarification email as a reply.

        Returns:
        {
          "sent": bool,
          "gmail_message_id": str | None
        }
        """

        stm = self.stm_manager.get(thread_id)
        if not stm:
            raise RuntimeError("STM record not found for thread")

        # -------------------------------
        # STM Guards (IDEMPOTENCY)
        # -------------------------------
        if stm.get("clarification_sent_at"):
            return {
                "sent": False,
                "gmail_message_id": None
            }

        if stm.get("state") != "AWAITING_CLARIFICATION":
            return {
                "sent": False,
                "gmail_message_id": None
            }

        if not clarification_question:
            raise ValueError("Clarification question is empty")

        # -------------------------------
        # Build Email
        # -------------------------------
        subject = original_subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        msg = EmailMessage()
        msg["To"] = supplier_email_id
        msg["From"] = sender_display_name
        msg["Subject"] = subject

        # Threading headers (CRITICAL)
        msg["In-Reply-To"] = original_email_id
        msg["References"] = original_email_id

        msg.set_content(
            f"""Hello,

{clarification_question}

Thank you,
{sender_display_name}
"""
        )

        # Encode message
        raw_message = base64.urlsafe_b64encode(
            msg.as_bytes()
        ).decode("utf-8")

        # -------------------------------
        # Send via Gmail API
        # -------------------------------
        sent_message = self.gmail_service.users().messages().send(
            userId="me",
            body={
                "raw": raw_message,
                "threadId": thread_id
            }
        ).execute()

        # -------------------------------
        # Update STM (mark sent)
        # -------------------------------
        now = datetime.now(timezone.utc).isoformat()
        stm["clarification_sent_at"] = now
        stm["last_updated"] = now

        self.stm_manager.create_or_update(stm)

        return {
            "sent": True,
            "gmail_message_id": sent_message.get("id")
        }
