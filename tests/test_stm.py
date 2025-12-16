from src.agents.stm_manager import STMManager

stm_mgr = STMManager()

thread_id = "19b22c0d8cc9025c"

stm = {
    "thread_id": thread_id,
    "supplier_id": "zenith-supplies.com",
    "supplier_email_ids": ["accounts@zenith-supplies.com"],
    "state": "AMBIGUOUS_PENDING",
    "email_trail": [],
    "pending_question": None,
    "last_classification": "AMBIGUOUS",
    "confidence": 0.72
}

stm_mgr.create_or_update(stm)

print("STM FROM REDIS:")
print(stm_mgr.get(thread_id))
