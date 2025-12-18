"""
Manual harness to exercise the dispute claim extractor agent.

Usage:
    python tests/manual_dispute_claim_extractor_demo.py

Requires:
    - OPENAI_API_KEY (and optional OPENAI_MODEL) set in env / .env
"""

from __future__ import annotations

import json

from src.agents.dispute_claim_extractor import extract_dispute_claim


def build_sample_processed_email() -> dict:
    return {
        "email_id": "sample-email-1",
        "thread_id": "sample-thread-1",
        "supplier_email_id": "mallickaryan1104@gmail.com",
        "supplier_id": "gmail.com",
        "sender_type": "EXTERNAL",
        "clean_text": (
            "Subject: Invoice INV-1001 short payment\n\n"
            "Hi AP team,\n\n"
            "We received only 10,000 INR against invoice INV-1001 (PO PO-2001) but the "
            "invoice total is 12,500 INR. Please confirm the balance or issue a credit note.\n\n"
            "Thanks,\nSupplier"
        ),
        "metadata": {
            "has_links": False,
            "has_images": False,
            "is_system_email": False,
            "language": "en",
        },
    }


def main() -> None:
    processed_email = build_sample_processed_email()
    result = extract_dispute_claim(processed_email)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

