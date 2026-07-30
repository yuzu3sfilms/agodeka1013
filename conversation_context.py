"""Per-request conversation context bridge for Project AGO v14.25.

DialogueManager resolves omitted subjects before DynamicSearch runs.
A ContextVar keeps the value isolated to the current request/thread.
"""
from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy

_DEFAULT = {
    "chat_id": "",
    "raw_query": "",
    "resolved_query": "",
    "resolved_subject": "",
    "follow_up_question": False,
    "subject_inherited": False,
    "topic_shift": False,
    "topic_stack": [],
    "relation": "new_topic",
    "confidence": 0.0,
}

_CURRENT_CONTEXT: ContextVar[dict] = ContextVar(
    "ago_v14_25_conversation_context",
    default=deepcopy(_DEFAULT),
)


def set_context(data: dict | None) -> dict:
    merged = deepcopy(_DEFAULT)
    if data:
        merged.update(data)
    _CURRENT_CONTEXT.set(merged)
    return deepcopy(merged)


def get_context() -> dict:
    return deepcopy(_CURRENT_CONTEXT.get())


def resolve_query(raw_query: str) -> tuple[str, dict]:
    raw = (raw_query or "").strip()
    ctx = get_context()
    if ctx.get("raw_query") == raw and ctx.get("resolved_query"):
        return str(ctx["resolved_query"]), ctx
    return raw, ctx
