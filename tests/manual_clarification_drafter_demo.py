"""
Manual test helper for the clarification email drafter.

Run:
    python tests/manual_clarification_drafter_demo.py

Prereqs:
- Redis running locally (STMManager default)
- OPENAI_API_KEY (and optionally OPENAI_MODEL) set in environment / .env

The script seeds a demo STM record, calls the LLM-powered drafter,
and prints the resulting clarification question + email body.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.agents.clarification_drafter import draft_clarification_email
from src.agents.stm_manager import STMManager


THREAD_ID = "demo-thread-clarification"


def seed_stm() -> None:
    """Create a demo STM record in Redis for the thread."""
    now = datetime.now(timezone.utc).isoformat()
    stm_manager = STMManager()
    # Clean out any previous demo data so each run is fresh.
    stm_manager.delete(THREAD_ID)

    record = {
        "thread_id": THREAD_ID,
        "supplier_id": "SUP-12345",
        "supplier_email_ids": ["supplier@example.com"],
        "state": "AWAITING_CLARIFICATION",
        "email_trail": [
            {
                "email_id": "demo-email-1",
                "message_id_header": "<demo-msg-1@example.com>",
                "timestamp": now,
                "classification": "AMBIGUOUS",
                "summary": "Initial email lacking invoice details.",
            }
        ],
        "original_clean_text": (
            "Hi team,\nWe noticed the latest payment seems short but I cannot locate the exact "
            "invoice reference. Can you confirm whether INV-9087 was settled?"
        ),
        "pending_question": None,
        "pending_draft_body": None,
        "last_classification": "AMBIGUOUS",
        "confidence": 0.51,
        "created_at": now,
        "last_updated": now,
    }
    stm_manager.create_or_update(record)


def main() -> None:
    seed_stm()

    processed_email = {
        "email_id": "demo-email-2",
        "thread_id": THREAD_ID,
        "clean_text": (
            "Following up on the earlier note—we still believe a deduction was taken on a "
            "recent payment, but we are unsure which invoice it relates to."
        ),
        "supplier_id": "SUP-12345",
        "supplier_email_id": "supplier@example.com",
    }

    ambiguity_summary = "Supplier hints at a short payment but no invoice or amount was provided."
    confidence = 0.47

    draft = draft_clarification_email(
        processed_email=processed_email,
        ambiguity_summary=ambiguity_summary,
        confidence=confidence,
    )

    print("\nClarification Drafter Output:")
    print(json.dumps(draft, indent=2))


if __name__ == "__main__":
    main()

