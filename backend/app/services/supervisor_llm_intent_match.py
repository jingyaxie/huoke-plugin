"""已废弃：请使用 lead_evaluation_service。"""
from __future__ import annotations

from typing import Any

from app.services.lead_evaluation_service import (
    accept_evaluation_result as accept_llm_intent_result,
    evaluate_comments_batch as classify_comments_llm_intent,
)
from app.services.task_brief_service import TaskBrief


def is_llm_intent_spec(spec: dict[str, Any] | None) -> bool:
    if not isinstance(spec, dict):
        return False
    return str(spec.get("schema") or "") == "huoke.lead_evaluation.v1"
