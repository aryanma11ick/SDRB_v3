from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from psycopg2.extras import RealDictCursor

from src.db.postgres import db_connection

AMOUNT_TOLERANCE = Decimal("1.00")  # INR tolerance; adjust per currency


@dataclass
class DisputeResolution:
    dispute_valid: bool
    resolution_reason: str
    supplier_id: int
    invoice_id: Optional[int]
    invoice_number: Optional[str]
    claimed_amount: Optional[Decimal]
    sap_amount: Optional[Decimal]
    dispute_case_row: dict[str, Any]
    supplier_ltm_row: dict[str, Any] | None


def _fetch_supplier_id(cursor: RealDictCursor, supplier_email: str) -> int:
    cursor.execute(
        """
        SELECT supplier_id
        FROM suppliers
        WHERE LOWER(supplier_email) = LOWER(%s)
        """,
        (supplier_email,),
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"Supplier not found for email {supplier_email}")
    return row["supplier_id"]


def _fetch_invoice(cursor: RealDictCursor, supplier_id: int, invoice_number: str) -> dict | None:
    cursor.execute(
        """
        SELECT invoice_id, invoice_number, supplier_id, invoice_amount, currency
        FROM invoices
        WHERE supplier_id = %s
          AND invoice_number = %s
        """,
        (supplier_id, invoice_number),
    )
    return cursor.fetchone()


def _upsert_supplier_ltm(cursor: RealDictCursor, supplier_id: int) -> None:
    cursor.execute(
        """
        INSERT INTO supplier_ltm (supplier_id)
        VALUES (%s)
        ON CONFLICT (supplier_id) DO NOTHING
        """,
        (supplier_id,),
    )


def _update_supplier_ltm(cursor: RealDictCursor, supplier_id: int, dispute_valid: bool) -> dict[str, Any]:
    cursor.execute(
        """
        UPDATE supplier_ltm
        SET
            total_disputes = total_disputes + 1,
            valid_disputes = valid_disputes + CASE WHEN %s THEN 1 ELSE 0 END,
            fake_disputes = fake_disputes + CASE WHEN %s THEN 1 ELSE 0 END,
            risk_score = CASE
                WHEN (total_disputes + 1) = 0 THEN 0
                ELSE ROUND(
                    ((fake_disputes + CASE WHEN %s THEN 1 ELSE 0 END)::numeric
                    / (total_disputes + 1)::numeric) * 100,
                    2
                )
            END,
            first_dispute_at = COALESCE(first_dispute_at, CURRENT_TIMESTAMP),
            last_dispute_at = CURRENT_TIMESTAMP,
            disputes_per_30d = ROUND(
                ((total_disputes + 1)::numeric) /
                GREATEST(
                    (EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - COALESCE(first_dispute_at, CURRENT_TIMESTAMP))) / 86400.0) / 30.0,
                    1.0
                ),
                2
            )
        WHERE supplier_id = %s
        RETURNING *;
        """,
        (dispute_valid, not dispute_valid, not dispute_valid, supplier_id),
    )
    base_row = cursor.fetchone()
    rolling = _calculate_rolling_metrics(cursor, supplier_id)
    cursor.execute(
        """
        UPDATE supplier_ltm
        SET
            rolling_30d_total = %(total_30d)s,
            rolling_30d_valid = %(valid_30d)s,
            rolling_30d_fake = %(fake_30d)s,
            rolling_30d_amount = %(amount_30d)s,
            rolling_30d_risk = %(risk_30d)s,
            rolling_90d_total = %(total_90d)s,
            rolling_90d_valid = %(valid_90d)s,
            rolling_90d_fake = %(fake_90d)s,
            rolling_90d_amount = %(amount_90d)s,
            rolling_90d_risk = %(risk_90d)s
        WHERE supplier_id = %(supplier_id)s
        RETURNING *;
        """,
        rolling,
    )
    return cursor.fetchone()


def _calculate_rolling_metrics(cursor: RealDictCursor, supplier_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        WITH stats AS (
            SELECT
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days') AS total_30d,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' AND dispute_valid) AS valid_30d,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' AND NOT dispute_valid) AS fake_30d,
                COALESCE(SUM(CASE WHEN created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN claimed_amount END), 0)::NUMERIC(14,2) AS amount_30d,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days') AS total_90d,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days' AND dispute_valid) AS valid_90d,
                COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days' AND NOT dispute_valid) AS fake_90d,
                COALESCE(SUM(CASE WHEN created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days' THEN claimed_amount END), 0)::NUMERIC(14,2) AS amount_90d
            FROM dispute_cases
            WHERE supplier_id = %s
        )
        SELECT * FROM stats;
        """,
        (supplier_id,),
    )
    stats = cursor.fetchone() or {}

    total_30d = stats.get("total_30d", 0) or 0
    fake_30d = stats.get("fake_30d", 0) or 0
    total_90d = stats.get("total_90d", 0) or 0
    fake_90d = stats.get("fake_90d", 0) or 0

    risk_30d = round((fake_30d / total_30d) * 100, 2) if total_30d else 0.0
    risk_90d = round((fake_90d / total_90d) * 100, 2) if total_90d else 0.0

    return {
        "supplier_id": supplier_id,
        "total_30d": total_30d,
        "valid_30d": stats.get("valid_30d", 0) or 0,
        "fake_30d": fake_30d,
        "amount_30d": stats.get("amount_30d") or Decimal("0.00"),
        "risk_30d": risk_30d,
        "total_90d": total_90d,
        "valid_90d": stats.get("valid_90d", 0) or 0,
        "fake_90d": fake_90d,
        "amount_90d": stats.get("amount_90d") or Decimal("0.00"),
        "risk_90d": risk_90d,
    }


def resolve_dispute_case(
    processed_email: dict,
    claim: dict,
    classification_confidence: float,
) -> DisputeResolution:
    supplier_email = processed_email.get("supplier_email_id")
    if not supplier_email:
        raise ValueError("Missing supplier_email_id in processed email")

    primary_invoice = claim.get("primary_invoice") or {}
    invoice_number = primary_invoice.get("invoice_number")
    claimed_amount_value = primary_invoice.get("claimed_amount_value")

    claimed_amount = Decimal(str(claimed_amount_value)) if claimed_amount_value is not None else None

    if not invoice_number:
        return DisputeResolution(
            dispute_valid=False,
            resolution_reason="MISSING_INVOICE_NUMBER",
            supplier_id=-1,
            invoice_id=None,
            invoice_number=None,
            claimed_amount=claimed_amount,
            sap_amount=None,
            dispute_case_row={},
            supplier_ltm_row=None,
        )

    with db_connection() as conn:
        with conn.cursor() as cursor:
            supplier_id = _fetch_supplier_id(cursor, supplier_email)
            invoice_row = _fetch_invoice(cursor, supplier_id, invoice_number)

            if not invoice_row:
                dispute_valid = False
                resolution_reason = "INVOICE_NOT_FOUND"
                sap_amount = None
                invoice_id = None
            else:
                sap_amount = invoice_row["invoice_amount"]
                invoice_id = invoice_row["invoice_id"]

                if claimed_amount is None:
                    dispute_valid = False
                    resolution_reason = "CLAIM_AMOUNT_MISSING"
                else:
                    difference = abs(claimed_amount - Decimal(sap_amount))
                    if difference > AMOUNT_TOLERANCE:
                        dispute_valid = True
                        resolution_reason = "AMOUNT_MISMATCH_VALID"
                    else:
                        dispute_valid = False
                        resolution_reason = "AMOUNT_MISMATCH_INVALID"

            cursor.execute(
                """
                INSERT INTO dispute_cases (
                    supplier_id,
                    invoice_id,
                    invoice_number,
                    claimed_amount,
                    sap_amount,
                    dispute_valid,
                    confidence_score,
                    resolution_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
                """,
                (
                    supplier_id,
                    invoice_id,
                    invoice_number,
                    claimed_amount,
                    sap_amount,
                    dispute_valid,
                    classification_confidence,
                    resolution_reason,
                ),
            )
            dispute_case_row = cursor.fetchone()

            _upsert_supplier_ltm(cursor, supplier_id)
            supplier_ltm_row = _update_supplier_ltm(cursor, supplier_id, dispute_valid)

        conn.commit()

    return DisputeResolution(
        dispute_valid=dispute_valid,
        resolution_reason=resolution_reason,
        supplier_id=supplier_id,
        invoice_id=invoice_id,
        invoice_number=invoice_number,
        claimed_amount=claimed_amount,
        sap_amount=sap_amount,
        dispute_case_row=dispute_case_row,
        supplier_ltm_row=supplier_ltm_row,
    )
