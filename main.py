import json
from datetime import datetime, timezone

from src.agents.gmail_watcher import fetch_emails
from src.agents.email_preprocessor import preprocess_email_llm
from src.agents.dispute_detector import detect_dispute
from src.agents.stm_manager import STMManager
from src.agents.ambiguity_resolver import resolve_ambiguity
from src.agents.clarification_mailer import ClarificationMailerAgent

stm_manager = STMManager()
mailer = ClarificationMailerAgent()


if __name__ == "__main__":
    emails = fetch_emails(limit=5)

    for email in emails:
        print("=" * 80)
        print("RAW EMAIL")
        print(json.dumps(email, indent=2))

        processed = preprocess_email_llm(email)
        # Preserve the RFC Message-ID header for threading replies later
        processed["message_id_header"] = email.get("message_id_header")
        print("\nPREPROCESSED")
        print(json.dumps(processed, indent=2))

        if processed["sender_type"] == "SYSTEM":
            print("⏭️ Skipping SYSTEM email")
            continue

        decision = detect_dispute(processed)
        print("\nDISPUTE DETECTION RESULT")
        print(json.dumps(decision, indent=2))

        print("DEBUG — classification:", decision["classification"])
        print("DEBUG — thread_id:", processed["thread_id"])

        # ==========================================================
        # HANDLE AMBIGUOUS EMAILS
        # ==========================================================
        if decision["classification"] == "AMBIGUOUS":
            thread_id = processed["thread_id"]
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
                question = resolve_ambiguity(
                    processed_email=processed,
                    ambiguity_summary=decision["reason"],
                    confidence=decision["confidence"]
                )
                print("\n🔍 AMBIGUITY RESOLVER OUTPUT")
                print(question)
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
                print("📧 Sending clarification email...")

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

                result = mailer.send_clarification(
                    thread_id=thread_id,
                    original_email_id=original_email_id,
                    original_message_id_header=original_message_id_header,
                    supplier_email_id=supplier_email_id,
                    original_subject=processed["clean_text"].split("\n")[0],
                    clarification_question=pending_question
                )

                print("📧 Clarification email result:", result)

        print("=" * 80, "\n")
