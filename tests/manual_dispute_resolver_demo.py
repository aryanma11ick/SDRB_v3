"""
Manual test for the deterministic dispute resolver.

Prereqs:
- Postgres populated with suppliers/invoices (see db/seed scripts)
- env vars DB_NAME/DB_USERNAME/DB_PASSWORD set (or in .env)

Usage:
    python tests/manual_dispute_resolver_demo.py
"""

from __future__ import annotations

from src.agents.dispute_claim_extractor import extract_dispute_claim
from src.services.dispute_resolver import resolve_dispute_case


def build_processed_email() -> dict:
    return {
        "email_id": "demo-email-2",
        "thread_id": "demo-thread-2",
        "supplier_email_id": "mallickaryan1104@gmail.com",
        "supplier_id": "gmail.com",
        "sender_type": "EXTERNAL",
        "clean_text": (
            "Subject: Short payment for INV-1001\n\n"
            "Hello,\nWe received only 10,000 INR against invoice INV-1001 (PO-2001) "
            "even though SAP shows 12,500 INR. Please reconcile the difference.\nThanks."
        ),
        "metadata": {
            "has_links": False,
            "has_images": False,
            "is_system_email": False,
            "language": "en",
        },
    }


def main() -> None:
    processed_email = build_processed_email()
    claim = extract_dispute_claim(processed_email)
    result = resolve_dispute_case(
        processed_email=processed_email,
        claim=claim,
        classification_confidence=0.85,
    )
    print("Dispute valid:", result.dispute_valid)
    print("Reason:", result.resolution_reason)
    print("Dispute case row:", result.dispute_case_row)
    print("Supplier LTM row:", result.supplier_ltm_row)


if __name__ == "__main__":
    main()

