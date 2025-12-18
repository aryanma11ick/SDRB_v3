from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from src.agents.stm_manager import STMManager

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

client = OpenAI(api_key=OPENAI_API_KEY)

PROMPT_PATH = Path("src/prompts/clarification_email_drafter.txt")


def _validate_draft(payload: dict[str, Any]) -> tuple[str, str]:
    question = payload.get("clarification_question")
    body_text = payload.get("body_text")

    if not isinstance(question, str) or not question.strip():
        raise RuntimeError("Clarification drafter returned missing clarification_question")
    if not isinstance(body_text, str) or not body_text.strip():
        raise RuntimeError("Clarification drafter returned missing body_text")

    question = question.strip()
    body_text = body_text.strip()

    # Heuristic guard: try to keep it single-question.
    if body_text.count("?") > 1:
        raise RuntimeError("Clarification drafter produced multiple questions")

    return question, body_text


def draft_clarification_email(
    processed_email: dict,
    ambiguity_summary: str,
    confidence: float,
    sender_display_name: str = "Accounts Payable Team",
) -> dict[str, str]:
    """
    Drafts a clarification email reply (question + full body) and stores it in STM.

    Returns:
      {
        "clarification_question": str,
        "body_text": str
      }
    """

    thread_id = processed_email.get("thread_id")
    if not thread_id:
        raise ValueError("Missing thread_id in processed_email")

    stm_manager = STMManager()
    stm = stm_manager.get(thread_id)
    if not stm:
        raise RuntimeError("STM record not found for ambiguous thread")

    # If we already have a pending draft, reuse it (idempotency).
    pending_question = stm.get("pending_question")
    pending_body = stm.get("pending_draft_body")
    if isinstance(pending_question, str) and pending_question.strip() and isinstance(pending_body, str) and pending_body.strip():
        return {
            "clarification_question": pending_question.strip(),
            "body_text": pending_body.strip(),
        }

    if stm.get("state") != "AWAITING_CLARIFICATION":
        raise RuntimeError("Thread is not awaiting clarification")

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    thread_context_obj = {
        "original_clean_text": stm.get("original_clean_text"),
        "email_trail": stm.get("email_trail"),
        "prior_pending_question": stm.get("pending_question"),
        "last_classification": stm.get("last_classification"),
        "state": stm.get("state"),
    }
    thread_context = json.dumps(thread_context_obj, ensure_ascii=False, indent=2)

    filled_prompt = (
        prompt_template
        .replace("<<<CLEAN_TEXT>>>", processed_email.get("clean_text", ""))
        .replace("<<<SUMMARY>>>", ambiguity_summary)
        .replace("<<<CONFIDENCE>>>", str(confidence))
        .replace("<<<THREAD_CONTEXT>>>", thread_context)
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0,
    )

    message_content = response.choices[0].message.content
    if message_content is None:
        raise RuntimeError("Clarification drafter returned empty response")
    content = message_content.strip()

    try:
        result: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError("Clarification drafter returned invalid JSON")

    question, body_text = _validate_draft(result)

    # Ensure the body contains the question (helps avoid mismatch).
    if question not in body_text:
        body_text = f"Hello,\n\n{question}\n\nThank you,\n{sender_display_name}"

    now = datetime.now(timezone.utc).isoformat()
    stm["pending_question"] = question
    stm["pending_draft_body"] = body_text
    stm["last_updated"] = now
    stm_manager.create_or_update(stm)

    return {
        "clarification_question": question,
        "body_text": body_text,
    }

