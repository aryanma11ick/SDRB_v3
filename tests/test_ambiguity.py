from src.agents.ambiguity_resolver import resolve_ambiguity
from src.agents.stm_manager import STMManager

stm_mgr = STMManager()
thread_id = "19b22c0d8cc9025c"

stm = stm_mgr.get(thread_id)

if stm is None:
    print("Error: STM not found for thread_id")
    exit(1)

processed_email = {
    "thread_id": thread_id,
    "clean_text": "We noticed a few differences compared to our internal records."
}

question = resolve_ambiguity(
    processed_email=processed_email,
    ambiguity_summary=stm["email_trail"][0]["summary"],
    confidence=stm["confidence"]
)

print(question)