import json
import os
from email.utils import parseaddr
from pathlib import Path

from src.utils.llm_client import get_default_model, get_openai_client

OPENAI_MODEL = get_default_model()
EMAIL_SYSTEM_ID = os.getenv("SYSTEM_EMAIL_ID")

client = get_openai_client()

PROMPT_PATH = Path("src/prompts/email_preprocessor.txt")


def _extract_sender_header(raw_email: dict) -> tuple[str | None, str | None]:
    """Return (email, domain) parsed from the Gmail header."""
    from_header = raw_email.get("from")
    if not isinstance(from_header, str):
        return None, None

    _display, email_address = parseaddr(from_header)
    if not email_address:
        return None, None

    email_address = email_address.strip()
    if not email_address:
        return None, None

    normalized_email = email_address.lower()
    domain = normalized_email.split("@")[-1] if "@" in normalized_email else None
    if domain:
        domain = domain.lower()

    return normalized_email, domain


def preprocess_email_llm(raw_email: dict) -> dict:
    prompt = PROMPT_PATH.read_text()

    filled_prompt = prompt.replace(
        "<<<EMAIL_JSON>>>",
        json.dumps(raw_email, indent=2)
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("LLM returned empty content")

    content = content.strip()

    try:
        processed = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError("LLM returned invalid JSON")

    sender_email, sender_domain = _extract_sender_header(raw_email)
    if sender_email:
        processed["supplier_email_id"] = sender_email
    if sender_domain:
        processed["supplier_id"] = sender_domain

    # =====================================================
    # HARD OVERRIDE: SYSTEM EMAIL DETECTION
    # =====================================================
    sender_email = processed.get("supplier_email_id")

    if (
        sender_email
        and EMAIL_SYSTEM_ID
        and sender_email.lower() == EMAIL_SYSTEM_ID.lower()
    ):
        processed["sender_type"] = "SYSTEM"
        processed["metadata"]["is_system_email"] = True

    return processed
