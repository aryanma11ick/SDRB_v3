import json
import time
from datetime import datetime, timezone

from src.agents.gmail_watcher import (
    fetch_emails,
    get_gmail_service,
    get_or_create_label,
    mark_labels,
    DISPUTE_LABEL_NAME,
    NON_DISPUTE_LABEL_NAME,
    PROCESSED_LABEL_NAME,
)
from src.agents.email_preprocessor import preprocess_email_llm
from src.agents.dispute_detector import detect_dispute
from src.agents.dispute_claim_extractor import extract_dispute_claim
from src.agents.stm_manager import STMManager
from src.agents.ambiguity_resolver import resolve_ambiguity
from src.agents.clarification_drafter import draft_clarification_email
from src.agents.clarification_mailer import ClarificationMailerAgent
from src.services.dispute_resolver import resolve_dispute_case


stm_manager = STMManager()
mailer = ClarificationMailerAgent()
PROCESSED_SET_KEY = "processed:email_ids"


def resolve_and_persist_dispute(processed_email: dict, decision: dict) -> None:
    """
    Extracts the structured claim, resolves it against Postgres/SAP data,
    and prints the outcome. Errors are swallowed so the pipeline keeps running.
    """
    try:
        claim = extract_dispute_claim(processed_email)
        result = resolve_dispute_case(
            processed_email=processed_email,
            claim=claim,
            classification_confidence=decision.get("confidence", 0.0),
        )
        print("\nDISPUTE RESOLUTION RESULT")
        printable = {
            "dispute_valid": result.dispute_valid,
            "resolution_reason": result.resolution_reason,
            "supplier_id": result.supplier_id,
            "invoice_id": result.invoice_id,
            "invoice_number": result.invoice_number,
            "claimed_amount": str(result.claimed_amount) if result.claimed_amount is not None else None,
            "sap_amount": str(result.sap_amount) if result.sap_amount is not None else None,
            "dispute_case_id": result.dispute_case_row.get("case_id") if result.dispute_case_row else None,
            "ltm_snapshot": result.supplier_ltm_row,
        }
        print(json.dumps(printable, indent=2, default=str))
    except Exception as exc:  # keep pipeline alive
        print("Failed to resolve dispute:", exc)


def process_email(email: dict) -> str | None:
    print("=" * 80)
    print("RAW EMAIL")
    print(json.dumps(email, indent=2))

    processed = preprocess_email_llm(email)
    # Preserve the RFC Message-ID header for threading replies
    processed["message_id_header"] = email.get("message_id_header")
    print("\nPREPROCESSED")
    print(json.dumps(processed, indent=2))

    if processed["sender_type"] == "SYSTEM":
        print("Skipping SYSTEM email")
        print("=" * 80, "\n")
        return "SYSTEM"

    thread_id = processed["thread_id"]
    stm = stm_manager.get(thread_id)

    # ==========================================================
    # RE-EVALUATE WITH CONTEXT (follow-up after clarification)
    # ==========================================================
    resolving_ambiguity = (
        stm
        and stm.get("state") == "AWAITING_CLARIFICATION"
        and stm.get("pending_question")
    )

    if resolving_ambiguity:
        # Combine original email + clarification question + reply for richer classification
        if stm is None:
            raise RuntimeError("STM is None but resolving_ambiguity is True")
        context_text = (
            f"Original email:\n{stm.get('original_clean_text', '')}\n\n"
            f"Clarification question sent:\n{stm.get('pending_question', '')}\n\n"
            f"Supplier reply:\n{processed['clean_text']}"
        )
        contextual_email = dict(processed)
        contextual_email["clean_text"] = context_text

        decision = detect_dispute(contextual_email)
        print("\nDISPUTE DETECTION RESULT (CONTEXTUAL)")
        print(json.dumps(decision, indent=2))

        now = datetime.now(timezone.utc).isoformat()
        email_trail = stm.get("email_trail") or []
        email_trail.append({
            "email_id": processed["email_id"],
            "message_id_header": processed.get("message_id_header"),
            "timestamp": now,
            "classification": decision["classification"],
            "summary": decision["reason"]
        })

        if stm is not None:
            stm["email_trail"] = email_trail
            stm["last_classification"] = decision["classification"]
        else:
            raise RuntimeError("STM is None, cannot update email trail.")
        stm["confidence"] = decision["confidence"]
        stm["last_updated"] = now
        stm["pending_question"] = None

        if decision["classification"] == "NON_DISPUTE":
            # Clear STM on non-dispute resolution
            stm_manager.delete(thread_id)
            print("=" * 80, "\n")
            return "NON_DISPUTE"

        if decision["classification"] == "DISPUTE":
            # Mark resolved with dispute; handoff can be added later
            stm["state"] = "RESOLVED_DISPUTE"
            stm_manager.create_or_update(stm)
            resolve_and_persist_dispute(processed, decision)
            stm_manager.delete(thread_id)
            print("=" * 80, "\n")
            return "DISPUTE"

        # If still ambiguous, keep STM and return classification
        stm_manager.create_or_update(stm)
        print("=" * 80, "\n")
        return decision["classification"]

    # ==========================================================
    # STANDARD CLASSIFICATION
    # ==========================================================
    decision = detect_dispute(processed)
    print("\nDISPUTE DETECTION RESULT")
    print(json.dumps(decision, indent=2))

    # Non-dispute: label + skip; clear any STM state if it exists
    if decision["classification"] == "NON_DISPUTE":
        if stm:
            stm_manager.delete(thread_id)
        print("=" * 80, "\n")
        return "NON_DISPUTE"

    if decision["classification"] == "DISPUTE":
        if stm:
            stm_manager.delete(thread_id)
        resolve_and_persist_dispute(processed, decision)
        print("=" * 80, "\n")
        return "DISPUTE"

    # ==========================================================
    # HANDLE AMBIGUOUS EMAILS
    # ==========================================================
    if decision["classification"] == "AMBIGUOUS":
        now = datetime.now(timezone.utc).isoformat()

        stm = stm_manager.get(thread_id)

        # -----------------------------
        # CREATE OR UPDATE STM
        # -----------------------------
        if not stm:
            stm = {
                "thread_id": thread_id,
                "supplier_id": processed["supplier_id"],
                "supplier_email_ids": [processed["supplier_email_id"]],
                "state": "AWAITING_CLARIFICATION",
                "email_trail": [],
                "original_clean_text": processed.get("clean_text"),
                "pending_question": None,
                "last_classification": decision["classification"],
                "confidence": decision["confidence"],
                "created_at": now,
                "last_updated": now
            }

        email_ids = {e["email_id"] for e in stm["email_trail"]}
        if processed["email_id"] not in email_ids:
            stm["email_trail"].append({
                "email_id": processed["email_id"],
                "message_id_header": processed.get("message_id_header"),
                "timestamp": now,
                "classification": decision["classification"],
                "summary": decision["reason"]
            })

        if processed["supplier_email_id"] not in stm["supplier_email_ids"]:
            stm["supplier_email_ids"].append(processed["supplier_email_id"])

        stm["last_classification"] = decision["classification"]
        stm["confidence"] = decision["confidence"]
        stm["last_updated"] = now

        stm_manager.create_or_update(stm)

        # -----------------------------
        # AMBIGUITY RESOLUTION (ONCE)
        # -----------------------------
        if not stm.get("pending_question"):
            draft = draft_clarification_email(
                processed_email=processed,
                ambiguity_summary=decision["reason"],
                confidence=decision["confidence"]
            )
            question = draft["clarification_question"]
            print("\nCLARIFICATION DRAFT OUTPUT")
            print(json.dumps(draft, indent=2))
        else:
            question = stm["pending_question"]

        # -----------------------------
        # SEND CLARIFICATION EMAIL (ONCE)
        # -----------------------------
        stm = stm_manager.get(thread_id)
        if stm is None:
            raise RuntimeError("STM record vanished before sending clarification")

        if (
            stm.get("state") == "AWAITING_CLARIFICATION"
            and stm.get("pending_question")
            and not stm.get("clarification_sent_at")
        ):
            print("Sending clarification email...")

            email_trail = stm.get("email_trail")
            if not isinstance(email_trail, list) or not email_trail:
                raise RuntimeError("STM missing email trail for clarification")
            first_email = email_trail[0]
            original_email_id = first_email.get("email_id")
            original_message_id_header = first_email.get("message_id_header")
            if not isinstance(original_email_id, str) or not original_email_id:
                raise RuntimeError("STM email trail missing email_id")

            supplier_email_ids = stm.get("supplier_email_ids")
            if not isinstance(supplier_email_ids, list) or not supplier_email_ids:
                raise RuntimeError("STM missing supplier email IDs for clarification")
            supplier_email_id = supplier_email_ids[0]
            if not isinstance(supplier_email_id, str) or not supplier_email_id:
                raise RuntimeError("STM supplier email ID invalid")

            pending_question = stm.get("pending_question")
            if not isinstance(pending_question, str) or not pending_question:
                raise RuntimeError("STM pending question missing or invalid")

            draft_body = stm.get("pending_draft_body")
            if draft_body is not None and not isinstance(draft_body, str):
                raise RuntimeError("STM pending draft body invalid")

            result = mailer.send_clarification(
                thread_id=thread_id,
                original_email_id=original_email_id,
                original_message_id_header=original_message_id_header,
                supplier_email_id=supplier_email_id,
                original_subject=processed["clean_text"].split("\n")[0],
                clarification_question=pending_question
                ,body_text=draft_body
            )

            print("Clarification email result:", result)

    print("=" * 80, "\n")
    return decision["classification"]


if __name__ == "__main__":
    seen_email_ids: set[str] = set()
    redis_client = stm_manager.redis
    gmail_service = get_gmail_service()
    processed_label_id = get_or_create_label(gmail_service, PROCESSED_LABEL_NAME)
    non_dispute_label_id = get_or_create_label(gmail_service, NON_DISPUTE_LABEL_NAME)
    dispute_label_id = get_or_create_label(gmail_service, DISPUTE_LABEL_NAME)

    print("Starting continuous processor. Press Ctrl+C to stop.")
    try:
        while True:
            emails = fetch_emails(limit=10)
            # Process only new emails not seen in this run and not marked processed in Redis
            new_emails = []
            for e in emails:
                email_id = e["email_id"]
                if email_id in seen_email_ids:
                    continue
                if redis_client.sismember(PROCESSED_SET_KEY, email_id):
                    continue
                new_emails.append(e)

            if new_emails:
                for email in new_emails:
                    seen_email_ids.add(email["email_id"])
                    try:
                        classification = process_email(email)
                        # Mark as processed in both Redis and Gmail labels
                        redis_client.sadd(PROCESSED_SET_KEY, email["email_id"])
                        labels_to_add = [processed_label_id]
                        if classification == "NON_DISPUTE":
                            labels_to_add.append(non_dispute_label_id)
                        if classification == "DISPUTE":
                            labels_to_add.append(dispute_label_id)
                        mark_labels(
                            service=gmail_service,
                            message_id=email["email_id"],
                            add_label_ids=labels_to_add
                        )
                    except Exception as exc:  # keep loop alive
                        print("Error processing email:", exc)
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nStopping processor.")
