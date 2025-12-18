from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils.llm_client import get_default_model, get_openai_client

OPENAI_MODEL = get_default_model()
client = get_openai_client()
PROMPT_PATH = Path("src/prompts/dispute_claim_extractor.txt")


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value).strip() or None


def _coerce_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Claim extractor returned non-object JSON")

    primary = payload.get("primary_invoice")
    if not isinstance(primary, dict):
        raise RuntimeError("primary_invoice missing or invalid")

    additional = payload.get("additional_invoices") or []
    if not isinstance(additional, list):
        raise RuntimeError("additional_invoices must be a list")

    normalized_additional: list[dict[str, Any]] = []
    for entry in additional:
        if not isinstance(entry, dict):
            continue
        normalized_additional.append(
            {
                "invoice_number": _coerce_str(entry.get("invoice_number")),
                "claimed_amount_value": _coerce_number(entry.get("claimed_amount_value")),
                "claimed_amount_currency": _coerce_str(entry.get("claimed_amount_currency")),
            }
        )

    result = {
        "primary_invoice": {
            "invoice_number": _coerce_str(primary.get("invoice_number")),
            "po_number": _coerce_str(primary.get("po_number")),
            "claimed_amount_value": _coerce_number(primary.get("claimed_amount_value")),
            "claimed_amount_currency": _coerce_str(primary.get("claimed_amount_currency")),
            "claimed_amount_text": _coerce_str(primary.get("claimed_amount_text")),
        },
        "additional_invoices": normalized_additional,
        "claimed_issue_summary": _coerce_str(payload.get("claimed_issue_summary")),
        "requested_action": _coerce_str(payload.get("requested_action")),
        "confidence": float(payload.get("confidence", 0.0) or 0.0),
        "missing_fields": payload.get("missing_fields") or [],
    }

    if not isinstance(result["missing_fields"], list):
        result["missing_fields"] = []

    return result


def extract_dispute_claim(processed_email: dict) -> dict[str, Any]:
    """
    Extracts structured dispute claim details from the preprocessed email.
    """

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    filled_prompt = prompt.replace(
        "<<<PROCESSED_EMAIL_JSON>>>",
        json.dumps(processed_email, indent=2),
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0,
    )

    message_content = response.choices[0].message.content
    if message_content is None:
        raise RuntimeError("Claim extractor returned empty response")

    message_content = message_content.strip()
    try:
        payload = json.loads(message_content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Claim extractor returned invalid JSON") from exc

    return _validate_payload(payload)
