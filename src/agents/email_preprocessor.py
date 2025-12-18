import json
import os
from pathlib import Path

from src.utils.llm_client import get_default_model, get_openai_client

OPENAI_MODEL = get_default_model()
EMAIL_SYSTEM_ID = os.getenv("SYSTEM_EMAIL_ID")

client = get_openai_client()

PROMPT_PATH = Path("src/prompts/email_preprocessor.txt")


def preprocess_email_llm(raw_email: dict) -> dict:
    prompt = PROMPT_PATH.read_text()

    filled_prompt = prompt.replace(
        "<<<EMAIL_JSON>>>",
        json.dumps(raw_email, indent=2)
    )

    response = client.chat.completions.create(
        model=OPENAPI_MODEL,
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
