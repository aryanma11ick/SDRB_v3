from __future__ import annotations

from typing import Any, TypedDict, cast

from src.agents.clarification_mailer import ClarificationMailerAgent
from src.agents.stm_manager import STMManager


class EmailTrailEntry(TypedDict):
    email_id: str
    summary: str


class STMRecord(TypedDict, total=False):
    thread_id: str
    state: str
    email_trail: list[EmailTrailEntry]
    supplier_email_ids: list[str]
    pending_question: str
    clarification_sent_at: str


stm_mgr = STMManager()
mailer = ClarificationMailerAgent()

thread_id = "19b2587f48b56565"
stm_raw = stm_mgr.get(thread_id)
if stm_raw is None:
    raise RuntimeError("STM record not found for test thread; seed the cache before running the test")
stm: STMRecord = cast(STMRecord, stm_raw)

email_trail = stm.get("email_trail")
if not isinstance(email_trail, list) or not email_trail:
    raise RuntimeError("STM record missing email trail data")
first_email = cast(EmailTrailEntry, email_trail[0])
original_email_id: str = first_email["email_id"]

supplier_email_ids = stm.get("supplier_email_ids")
if not isinstance(supplier_email_ids, list) or not supplier_email_ids:
    raise RuntimeError("STM record missing supplier email addresses")
supplier_email_id: str = supplier_email_ids[0]

pending_question = stm.get("pending_question")
if not isinstance(pending_question, str) or not pending_question:
    raise RuntimeError("STM record missing pending clarification question")

result = mailer.send_clarification(
    thread_id=thread_id,
    original_email_id=original_email_id,
    original_message_id_header=None,
    supplier_email_id=supplier_email_id,
    original_subject="Question regarding invoice",
    clarification_question=pending_question,
    body_text=cast(Any, stm).get("pending_draft_body")
)

print(result)
