import asyncio
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
from src.agents.context_resolution_agent import (
    ContextResolutionOutcome,
    resolve_conversational_context,
)
from src.services.dispute_resolver import resolve_dispute_case

stm_manager = STMManager()
mailer = ClarificationMailerAgent()
PROCESSED_SET_KEY = "processed:email_ids"


def _bootstrap_stm_from_email(
    processed_email: dict,
    classification: str,
    reason: str,
    state: str,
    confidence: float | None,
    thread_id: str | None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    supplier_email = processed_email.get("supplier_email_id")
    supplier_emails = [supplier_email] if supplier_email else []

    entry = {
        "email_id": processed_email.get("email_id"),
        "message_id_header": processed_email.get("message_id_header"),
        "timestamp": now,
        "classification": classification,
        "summary": reason,
    }

    return {
        "thread_id": thread_id,
        "supplier_id": processed_email.get("supplier_id"),
        "supplier_email_ids": supplier_emails,
        "state": state,
        "email_trail": [entry],
        "original_clean_text": processed_email.get("clean_text"),
        "pending_question": None,
        "pending_draft_body": None,
        "last_classification": classification,
        "confidence": confidence or 0.0,
        "created_at": now,
        "last_updated": now,
    }


def _append_email_trail_entry(stm: dict, processed_email: dict, classification: str, reason: str) -> None:
    if not stm:
        return
    stm.setdefault("email_trail", [])
    email_id = processed_email.get("email_id")
    existing_ids = {entry.get("email_id") for entry in stm["email_trail"]}
    if email_id in existing_ids:
        return

    stm["email_trail"].append({
        "email_id": email_id,
        "message_id_header": processed_email.get("message_id_header"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "summary": reason,
    })

    supplier_email = processed_email.get("supplier_email_id")
    if supplier_email:
        stm.setdefault("supplier_email_ids", [])
        if supplier_email not in stm["supplier_email_ids"]:
            stm["supplier_email_ids"].append(supplier_email)

    if not stm.get("original_clean_text"):
        stm["original_clean_text"] = processed_email.get("clean_text")


async def run_in_thread(func, *args, **kwargs):
    """Helper to run blocking functions in a thread pool."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def resolve_and_persist_dispute_async(processed_email: dict, decision: dict) -> None:
    try:
        claim = await run_in_thread(extract_dispute_claim, processed_email)
        result = await run_in_thread(
            resolve_dispute_case,
            processed_email,
            claim,
            decision.get("confidence", 0.0),
        )
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
        print("\nDISPUTE RESOLUTION RESULT (ASYNC)")
        print(json.dumps(printable, indent=2, default=str))
    except Exception as exc:
        print("Failed to resolve dispute (async):", exc)


async def process_email_async(email: dict) -> str | None:
    print("=" * 80)
    print("RAW EMAIL")
    print(json.dumps(email, indent=2))

    # Resolve conversational context using STM, similarity, and an AI agent before dispute classification.
    context_outcome: ContextResolutionOutcome = await run_in_thread(
        resolve_conversational_context,
        email,
        stm_manager,
    )
    context_log = {
        "email_id": email.get("email_id"),
        "stm_found": bool(context_outcome.stm),
        "similarity_score": context_outcome.similarity_score,
        "decision": context_outcome.decision,
    }
    email["resolved_context"] = {
        "decision": context_outcome.decision,
        "similarity_score": context_outcome.similarity_score,
        "notes": context_outcome.notes,
        "stm_thread_id": context_outcome.stm.get("thread_id") if context_outcome.stm else None,
    }
    conversation_thread_id = (
        context_outcome.stm.get("thread_id")
        if context_outcome.stm and context_outcome.stm.get("thread_id")
        else email.get("thread_id")
    )
    email["conversation_thread_id"] = conversation_thread_id

    for key, value in (context_outcome.inherited_fields or {}).items():
        if value and not email.get(key):
            email[key] = value
    print(f"[{context_log['email_id']}] Context resolution -> "
          f"STM: {context_log['stm_found']}, "
          f"similarity: {context_log['similarity_score']}, "
          f"decision: {context_log['decision']}")
    if context_outcome.skip_classification:
        print(f"[{context_log['email_id']}] Context agent marked NO_OP; skipping classification.")
        return "NO_OP"

    processed = await run_in_thread(preprocess_email_llm, email)
    processed["message_id_header"] = email.get("message_id_header")
    processed["gmail_thread_id"] = processed.get("thread_id")
    if conversation_thread_id:
        processed["thread_id"] = conversation_thread_id
    processed["resolved_context"] = email.get("resolved_context")
    for key in ("supplier_email_id", "supplier_id"):
        inherited_value = context_outcome.inherited_fields.get(key)
        if inherited_value and not processed.get(key):
            processed[key] = inherited_value
    print("\nPREPROCESSED")
    print(json.dumps(processed, indent=2))

    if processed["sender_type"] == "SYSTEM":
        print("Skipping SYSTEM email")
        print("=" * 80, "\n")
        return "SYSTEM"

    thread_id = processed["thread_id"]
    if context_outcome.stm and context_outcome.stm.get("thread_id") != thread_id:
        thread_id = context_outcome.stm.get("thread_id")
        processed["thread_id"] = thread_id
    stm = context_outcome.stm or await run_in_thread(stm_manager.get, thread_id)

    resolving_ambiguity = (
        stm
        and stm.get("state") == "AWAITING_CLARIFICATION"
        and stm.get("pending_question")
    )

    if resolving_ambiguity and stm:
        context_text = (
            f"Original email:\n{stm.get('original_clean_text', '')}\n\n"
            f"Clarification question sent:\n{stm.get('pending_question', '')}\n\n"
            f"Supplier reply:\n{processed['clean_text']}"
        )
        contextual_email = dict(processed)
        contextual_email["clean_text"] = context_text

        decision = await run_in_thread(detect_dispute, contextual_email)
        print("\nDISPUTE DETECTION RESULT (ASYNC CONTEXTUAL)")
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

        stm["email_trail"] = email_trail
        stm["last_classification"] = decision["classification"]
        stm["confidence"] = decision["confidence"]
        stm["last_updated"] = now
        stm["pending_question"] = None

        if decision["classification"] == "NON_DISPUTE":
            stm["state"] = "RESOLVED_NON_DISPUTE"
            await run_in_thread(stm_manager.create_or_update, stm)
            print("=" * 80, "\n")
            return "NON_DISPUTE"

        if decision["classification"] == "DISPUTE":
            stm["state"] = "RESOLVED_DISPUTE"
            await run_in_thread(stm_manager.create_or_update, stm)
            await resolve_and_persist_dispute_async(processed, decision)
            print("=" * 80, "\n")
            return "DISPUTE"

        await run_in_thread(stm_manager.create_or_update, stm)
        print("=" * 80, "\n")
        return decision["classification"]

    decision = await run_in_thread(detect_dispute, processed)
    print("\nDISPUTE DETECTION RESULT (ASYNC)")
    print(json.dumps(decision, indent=2))

    if decision["classification"] == "NON_DISPUTE":
        reason = decision.get("reason") or "UNSPECIFIED_REASON"
        if not stm:
            stm = _bootstrap_stm_from_email(
                processed,
                decision["classification"],
                reason,
                "RESOLVED_NON_DISPUTE",
                decision.get("confidence"),
                thread_id,
            )
        else:
            _append_email_trail_entry(stm, processed, decision["classification"], reason)
            stm["state"] = "RESOLVED_NON_DISPUTE"
        stm["last_classification"] = decision["classification"]
        stm["confidence"] = decision["confidence"]
        await run_in_thread(stm_manager.create_or_update, stm)
        print("=" * 80, "\n")
        return "NON_DISPUTE"

    if decision["classification"] == "DISPUTE":
        reason = decision.get("reason") or "UNSPECIFIED_REASON"
        if not stm:
            stm = _bootstrap_stm_from_email(
                processed,
                decision["classification"],
                reason,
                "RESOLVED_DISPUTE",
                decision.get("confidence"),
                thread_id,
            )
        else:
            _append_email_trail_entry(stm, processed, decision["classification"], reason)
            stm["state"] = "RESOLVED_DISPUTE"
        stm["last_classification"] = decision["classification"]
        stm["confidence"] = decision["confidence"]
        await run_in_thread(stm_manager.create_or_update, stm)
        await resolve_and_persist_dispute_async(processed, decision)
        print("=" * 80, "\n")
        return "DISPUTE"

    if decision["classification"] == "AMBIGUOUS":
        now = datetime.now(timezone.utc).isoformat()
        stm = stm or {
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

        if processed["supplier_email_id"] not in stm.get("supplier_email_ids", []):
            stm["supplier_email_ids"] = stm.get("supplier_email_ids", [])
            stm["supplier_email_ids"].append(processed["supplier_email_id"])

        stm["last_classification"] = decision["classification"]
        stm["confidence"] = decision["confidence"]
        stm["last_updated"] = now

        await run_in_thread(stm_manager.create_or_update, stm)

        if not stm.get("pending_question"):
            draft = await run_in_thread(
                draft_clarification_email,
                processed,
                decision["reason"],
                decision["confidence"]
            )
            print("\nCLARIFICATION DRAFT OUTPUT (ASYNC)")
            print(json.dumps(draft, indent=2))
        else:
            draft = {
                "clarification_question": stm["pending_question"],
                "body_text": stm.get("pending_draft_body")
            }

        refreshed_stm = await run_in_thread(stm_manager.get, thread_id)
        if (
            refreshed_stm
            and refreshed_stm.get("state") == "AWAITING_CLARIFICATION"
            and refreshed_stm.get("pending_question")
            and not refreshed_stm.get("clarification_sent_at")
        ):
            email_trail = refreshed_stm.get("email_trail")
            first_email = email_trail[0]
            result = await run_in_thread(
                mailer.send_clarification,
                thread_id=thread_id,
                original_email_id=first_email.get("email_id"),
                supplier_email_id=refreshed_stm["supplier_email_ids"][0],
                original_subject=processed["clean_text"].split("\n")[0],
                clarification_question=refreshed_stm["pending_question"],
                original_message_id_header=first_email.get("message_id_header"),
                body_text=refreshed_stm.get("pending_draft_body"),
            )
            print("Clarification email result (async):", result)

    print("=" * 80, "\n")
    return decision["classification"]


async def main():
    seen_email_ids: set[str] = set()
    redis_client = stm_manager.redis
    gmail_service = get_gmail_service()
    processed_label_id = get_or_create_label(gmail_service, PROCESSED_LABEL_NAME)
    non_dispute_label_id = get_or_create_label(gmail_service, NON_DISPUTE_LABEL_NAME)
    dispute_label_id = get_or_create_label(gmail_service, DISPUTE_LABEL_NAME)

    print("Starting async processor. Press Ctrl+C to stop.")
    try:
        while True:
            emails = fetch_emails(limit=10)
            new_emails = []
            for e in emails:
                email_id = e["email_id"]
                if email_id in seen_email_ids:
                    continue
                if redis_client.sismember(PROCESSED_SET_KEY, email_id):
                    continue
                new_emails.append(e)

            if new_emails:
                tasks = []
                for email in new_emails:
                    seen_email_ids.add(email["email_id"])
                    tasks.append(asyncio.create_task(process_email_async(email)))

                results = await asyncio.gather(*tasks, return_exceptions=True)
                for email, result in zip(new_emails, results):
                    email_id = email["email_id"]
                    redis_client.sadd(PROCESSED_SET_KEY, email_id)
                    if isinstance(result, Exception):
                        print("Error processing email:", result)
                        continue
                    labels_to_add = [processed_label_id]
                    if result == "NON_DISPUTE":
                        labels_to_add.append(non_dispute_label_id)
                    if result == "DISPUTE":
                        labels_to_add.append(dispute_label_id)
                    try:
                        mark_labels(
                            service=gmail_service,
                            message_id=email_id,
                            add_label_ids=labels_to_add
                        )
                    except Exception as exc:
                        print("Failed to mark labels:", exc)
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        print("\nStopping async processor.")


if __name__ == "__main__":
    asyncio.run(main())
