import json
from pathlib import Path
from datetime import datetime, timezone
import os
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

from src.agents.stm_manager import STMManager

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

PROMPT_PATH = Path("src/prompts/ambiguity_resolver.txt")


def resolve_ambiguity(
    processed_email: dict,
    ambiguity_summary: str,
    confidence: float
) -> str:
    """
    Generates a clarification question for an ambiguous email
    and stores it in STM.

    Returns:
      clarification_question (str)
    """

    thread_id = processed_email.get("thread_id")
    if not thread_id:
        raise ValueError("Missing thread_id in processed_email")

    stm_manager = STMManager()
    stm = stm_manager.get(thread_id)

    if not stm:
        raise RuntimeError("STM record not found for ambiguous thread")

    # Only resolve if clarification is still pending
    if stm["state"] != "AWAITING_CLARIFICATION":
        pending_question = stm.get("pending_question")
        if not isinstance(pending_question, str) or not pending_question:
            raise RuntimeError("Pending clarification question missing in STM")
        return pending_question

    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    filled_prompt = (
        prompt_template
        .replace("<<<CLEAN_TEXT>>>", processed_email["clean_text"])
        .replace("<<<SUMMARY>>>", ambiguity_summary)
        .replace("<<<CONFIDENCE>>>", str(confidence))
    )

    response = client.chat.completions.create(
        model="gpt-5.2",
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0
    )

    message_content = response.choices[0].message.content
    if message_content is None:
        raise RuntimeError("Ambiguity resolver returned empty response")
    content = message_content.strip()

    try:
        result: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError("Ambiguity resolver returned invalid JSON")

    question = result.get("clarification_question")
    if not isinstance(question, str) or not question.strip():
        raise RuntimeError("No clarification question generated")
    question = question.strip()

    # Update STM
    now = datetime.now(timezone.utc).isoformat()
    stm["pending_question"] = question
    stm["last_updated"] = now

    stm_manager.create_or_update(stm)

    return question
