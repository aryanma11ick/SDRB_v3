# Resolve conversational context using STM, similarity, and an AI agent before dispute classification.
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from src.utils.llm_client import get_default_model, get_openai_client

client = get_openai_client()
CONTEXT_MODEL = os.getenv("CONTEXT_RESOLUTION_MODEL", get_default_model())
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
PROMPT_PATH = Path("src/prompts/context_resolution_agent.txt")


@dataclass
class ContextResolutionOutcome:
    decision: str
    similarity_score: float | None
    stm: dict[str, Any] | None
    inherited_fields: dict[str, Any]
    skip_classification: bool
    notes: str | None


def _build_clean_candidate(raw_email: dict) -> str:
    subject = raw_email.get("subject") or ""
    body = raw_email.get("body") or ""
    combined = f"{subject}\n\n{body}".strip()
    return combined


def _extract_sender_email(raw_email: dict) -> str | None:
    sender = raw_email.get("supplier_email_id")
    if isinstance(sender, str) and sender.strip():
        return sender.strip().lower()

    from_header = raw_email.get("from")
    if not isinstance(from_header, str):
        return None
    _, email_addr = parseaddr(from_header)
    return email_addr.lower() if email_addr else None


def _generate_embedding(text: str) -> list[float]:
    if not text or not text.strip():
        return []
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text.strip(),
    )
    return response.data[0].embedding


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float | None:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return None
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def _collect_reference_texts(stm: dict[str, Any] | None) -> list[str]:
    if not stm:
        return []
    references: list[str] = []
    original = stm.get("original_clean_text")
    if isinstance(original, str) and original.strip():
        references.append(original.strip())
    trail = stm.get("email_trail") or []
    for entry in reversed(trail):
        summary = entry.get("summary")
        if isinstance(summary, str) and summary.strip():
            references.append(summary.strip())
        if len(references) >= 4:
            break
    return references


def _calculate_similarity(candidate_text: str, stm: dict[str, Any] | None) -> float | None:
    references = _collect_reference_texts(stm)
    if not references or not candidate_text.strip():
        return None
    candidate_embedding = _generate_embedding(candidate_text)
    if not candidate_embedding:
        return None
    similarities = []
    for text in references:
        ref_embedding = _generate_embedding(text)
        score = _cosine_similarity(candidate_embedding, ref_embedding)
        if score is not None:
            similarities.append(score)
    return max(similarities) if similarities else None


def _call_context_agent(payload: dict[str, Any]) -> dict[str, Any]:
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("<<<INPUT_JSON>>>", json.dumps(payload, ensure_ascii=False, indent=2))
    response = client.chat.completions.create(
        model=CONTEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("Context resolution agent returned empty response")
    content = content.strip()
    return json.loads(content)


def _merge_inherited_fields(stm: dict[str, Any], inherited: dict[str, Any]) -> None:
    supplier_email = inherited.get("supplier_email_id")
    supplier_domain = inherited.get("supplier_id")
    if supplier_email:
        stm.setdefault("supplier_email_ids", [])
        if supplier_email not in stm["supplier_email_ids"]:
            stm["supplier_email_ids"].append(supplier_email)
    if supplier_domain and not stm.get("supplier_id"):
        stm["supplier_id"] = supplier_domain
    for key, value in inherited.items():
        if key in {"supplier_email_id", "supplier_id"}:
            continue
        if value is None:
            continue
        if not stm.get(key):
            stm[key] = value


def _append_email_trail_entry(stm: dict[str, Any], raw_email: dict, tag: str) -> None:
    stm.setdefault("email_trail", [])
    existing_ids = {entry.get("email_id") for entry in stm["email_trail"]}
    email_id = raw_email.get("email_id")
    timestamp = raw_email.get("date") or raw_email.get("timestamp") or datetime.now(timezone.utc).isoformat()
    if email_id in existing_ids:
        return
    stm["email_trail"].append({
        "email_id": email_id,
        "message_id_header": raw_email.get("message_id_header"),
        "timestamp": timestamp,
        "classification": tag,
        "summary": raw_email.get("subject"),
    })


def resolve_conversational_context(raw_email: dict, stm_manager) -> ContextResolutionOutcome:
    candidate_text = _build_clean_candidate(raw_email)
    supplier_email = _extract_sender_email(raw_email)
    thread_id = raw_email.get("thread_id")

    stm = None
    stm_from_thread = stm_manager.get(thread_id) if thread_id else None
    stm_from_supplier = None
    if not stm_from_thread and supplier_email:
        stm_from_supplier = stm_manager.find_active_by_supplier_email(supplier_email)
    stm = stm_from_thread or stm_from_supplier

    similarity_score = _calculate_similarity(candidate_text, stm) if stm else None

    payload = {
        "email_id": raw_email.get("email_id"),
        "thread_id": thread_id,
        "has_thread_id": bool(thread_id),
        "supplier_email_id": supplier_email,
        "clean_text": candidate_text,
        "similarity_score": similarity_score,
        "stm_present": stm is not None,
        "stm_payload": stm,
    }

    default_decision = "CONTINUE" if stm else "NEW"
    try:
        agent_decision = _call_context_agent(payload)
    except Exception:
        agent_decision = {
            "decision": default_decision,
            "skip_classification": False,
            "inherited_fields": {},
            "notes": f"Agent fallback to {default_decision} due to error",
        }

    decision = str(agent_decision.get("decision", "NEW")).upper()
    if decision not in {"CONTINUE", "NEW", "NO_OP"}:
        decision = "NEW"

    inherited = agent_decision.get("inherited_fields") or {}
    skip_classification = bool(agent_decision.get("skip_classification", False))
    notes = agent_decision.get("notes")

    stm_to_return = stm
    if decision == "CONTINUE" and (similarity_score is None or similarity_score < 0.6):
        decision = "NEW"
        stm_to_return = None

    if decision == "CONTINUE" and stm:
        _merge_inherited_fields(stm, inherited)
        _append_email_trail_entry(stm, raw_email, "CONTEXT_CONTINUATION")
        stm_manager.create_or_update(stm)
    elif decision == "NO_OP" and stm:
        _append_email_trail_entry(stm, raw_email, "CONTEXT_NO_OP")
        stm_manager.create_or_update(stm)
    else:
        stm_to_return = None if decision != "CONTINUE" else stm

    return ContextResolutionOutcome(
        decision=decision,
        similarity_score=similarity_score,
        stm=stm_to_return,
        inherited_fields=inherited,
        skip_classification=skip_classification or decision == "NO_OP",
        notes=notes if isinstance(notes, str) else None,
    )
