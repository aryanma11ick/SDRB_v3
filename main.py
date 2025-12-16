import json
from src.agents.gmail_watcher import fetch_emails
from src.agents.email_preprocessor import preprocess_email_llm
from src.agents.dispute_detector import detect_dispute
from src.agents.stm_manager import STMManager
from datetime import datetime

stm_manager = STMManager()

if __name__ == "__main__":
    emails = fetch_emails(limit=5)

    for email in emails:
        print("=" * 80)
        print("RAW EMAIL")
        print(json.dumps(email, indent=2))

        processed = preprocess_email_llm(email)
        print("\nPREPROCESSED")
        print(json.dumps(processed, indent=2))

        decision = detect_dispute(processed)
        print("\n DISPUTE DETECTION RESULT")
        print(json.dumps(decision, indent=2))

        print("DEBUG — classification:", decision["classification"])
        print("DEBUG — thread_id:", processed["thread_id"])

        if decision["classification"] == "AMBIGUOUS":
            thread_id = processed["thread_id"]

            # Check if STM already exists
            existing_stm = stm_manager.get(thread_id)

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()


            if not existing_stm:
                # Create new STM record
                stm_record = {
                    "thread_id": thread_id,
                    "supplier_id": processed["supplier_id"],
                    "supplier_email_ids": [processed["supplier_email_id"]],
                    "state": "AWAITING_CLARIFICATION",
                    "email_trail": [
                        {
                            "email_id": processed["email_id"],
                            "timestamp": now,
                            "classification": decision["classification"],
                            "summary": decision["reason"]
                        }
                    ],
                    "pending_question": None,
                    "last_classification": decision["classification"],
                    "confidence": decision["confidence"]
                }

                stm_manager.create_or_update(stm_record)

            else:
                # Update existing STM
                existing_stm["email_trail"].append({
                    "email_id": processed["email_id"],
                    "timestamp": now,
                    "classification": decision["classification"],
                    "summary": decision["reason"]
                })

                # Track new sender if different
                if processed["supplier_email_id"] not in existing_stm["supplier_email_ids"]:
                    existing_stm["supplier_email_ids"].append(
                        processed["supplier_email_id"]
                    )

                existing_stm["last_classification"] = decision["classification"]
                existing_stm["confidence"] = decision["confidence"]

                stm_manager.create_or_update(existing_stm)


        print("=" * 80, "\n")
