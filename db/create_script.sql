-- schema_sdrb_phase1.sql
-- Run in pgAdmin: open Query Tool, paste, execute.

BEGIN;

CREATE TABLE suppliers (
    supplier_id     SERIAL PRIMARY KEY,
    supplier_name   TEXT        NOT NULL,
    supplier_email  TEXT        UNIQUE NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'ACTIVE',
    created_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE invoices (
    invoice_id      SERIAL PRIMARY KEY,
    invoice_number  TEXT        NOT NULL,
    supplier_id     INT         NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    po_number       TEXT,
    invoice_amount  NUMERIC(12,2) NOT NULL,
    currency        TEXT        NOT NULL DEFAULT 'INR',
    invoice_date    DATE,
    status          TEXT        NOT NULL DEFAULT 'POSTED',
    CONSTRAINT invoices_supplier_invoice_uniq UNIQUE (supplier_id, invoice_number)
);

CREATE TABLE dispute_cases (
    case_id           SERIAL PRIMARY KEY,
    supplier_id       INT         NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    invoice_id        INT         REFERENCES invoices(invoice_id) ON DELETE SET NULL,
    invoice_number    TEXT,
    claimed_amount    NUMERIC(12,2),
    sap_amount        NUMERIC(12,2),
    dispute_valid     BOOLEAN     NOT NULL,
    confidence_score  NUMERIC(4,2),
    resolution_reason TEXT        NOT NULL,
    created_at        TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT dispute_invoice_ref_ck CHECK (
        invoice_id IS NOT NULL OR invoice_number IS NOT NULL
    )
);

CREATE TABLE supplier_ltm (
    supplier_id     INT PRIMARY KEY REFERENCES suppliers(supplier_id) ON DELETE CASCADE,
    total_disputes  INT           NOT NULL DEFAULT 0,
    valid_disputes  INT           NOT NULL DEFAULT 0,
    fake_disputes   INT           NOT NULL DEFAULT 0,
    risk_score      NUMERIC(4,2)  NOT NULL DEFAULT 0.00,
    last_updated    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- keep supplier_ltm.last_updated fresh on updates
CREATE OR REPLACE FUNCTION set_supplier_ltm_timestamp()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.last_updated := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TRIGGER supplier_ltm_updated_at
BEFORE UPDATE ON supplier_ltm
FOR EACH ROW
EXECUTE FUNCTION set_supplier_ltm_timestamp();

COMMIT;
