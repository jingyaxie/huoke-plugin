from __future__ import annotations

from typing import Any


def classify_skill_failure(result: dict[str, Any]) -> str | None:
    status = str(result.get("status") or "").lower()
    text = (
        f"{result.get('error') or ''} {result.get('reason') or ''} "
        f"{result.get('summary') or ''} {result.get('diagnostic') or ''}"
    ).lower()
    if status not in {"failed", "error"} and not result.get("error"):
        if status == "completed":
            return None
        if not result.get("error"):
            return None
    if any(k in text for k in ("验证码", "风控", "risk", "blocked", "429", "403")):
        return "risk_control"
    if any(k in text for k in ("登录", "login", "cookie", "storage_state", "binding")):
        return "login_required"
    if any(k in text for k in ("timeout", "超时", "未找到", "not found", "selector", "弹窗")):
        return "page_changed"
    if any(k in text for k in ("empty", "无数据", "no data", "列表为空", "未搜索到", "未抓取")):
        return "empty_data"
    return "generic_error"


def is_recoverable_failure(failure_type: str | None) -> bool:
    return failure_type in {"page_changed", "empty_data", "generic_error"}


def is_terminal_failure(failure_type: str | None) -> bool:
    return failure_type in {"risk_control", "login_required"}
