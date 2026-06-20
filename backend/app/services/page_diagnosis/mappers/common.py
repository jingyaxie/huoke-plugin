from __future__ import annotations

import re
from typing import Any, Protocol

from app.services.page_diagnosis.contracts import CrawlFailureSignal, FailureClass, Platform


class PlatformFailureMapper(Protocol):
    platform: Platform

    def map_skill_result(self, result: dict[str, Any], *, operation: str, implementation: str) -> CrawlFailureSignal: ...

    def map_exception(self, exc: Exception, *, operation: str, implementation: str) -> CrawlFailureSignal: ...


def _blob(result: dict[str, Any]) -> str:
    parts = [
        str(result.get("error") or ""),
        str(result.get("reason") or ""),
        str(result.get("summary") or ""),
        str(result.get("diagnostic") or ""),
        str(result.get("message") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _classify_text(text: str) -> FailureClass:
    lower = text.lower()
    if any(k in lower for k in ("验证码", "captcha", "人机验证", "verify_check", "滑块")):
        return "captcha"
    if any(k in lower for k in ("so-landing", "so_landing", "自动化浏览器", "automation")):
        return "automation_blocked"
    if any(k in lower for k in ("风控", "risk", "blocked", "429", "403", "频率", "限制")):
        return "risk_limit"
    if any(k in lower for k in ("游客", "visitor", "guest")):
        return "auth_required"
    if any(k in lower for k in ("登录", "login", "cookie", "storage_state", "扫码", "未检测到")):
        return "auth_required"
    if any(k in lower for k in ("过期", "expired", "失效", "invalid")):
        return "auth_expired"
    if any(k in lower for k in ("timeout", "超时", "timed out", "connect")):
        return "network"
    if any(k in lower for k in ("selector", "未找到", "not found", "弹窗", "page changed")):
        return "page_structure"
    if any(k in lower for k in ("empty", "无数据", "no data", "列表为空", "未搜索到", "未抓取", "0 条")):
        return "empty_result"
    if any(k in lower for k in ("typeerror", "attributeerror", "技能不存在", "missing")):
        return "internal"
    return "unknown"


def _is_recoverable(failure_class: FailureClass) -> bool:
    return failure_class in {"page_structure", "empty_result", "network", "unknown", "internal"}


def _base_signal(
    *,
    platform: Platform,
    operation: str,
    implementation: str,
    failure_class: FailureClass,
    message: str,
    guard_hints: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    page_available: bool = False,
) -> CrawlFailureSignal:
    return CrawlFailureSignal(
        platform=platform,
        operation=operation,
        implementation=implementation,
        failure_class=failure_class,
        message=message[:500],
        recoverable=_is_recoverable(failure_class),
        page_available=page_available,
        guard_hints=dict(guard_hints or {}),
        context=dict(context or {}),
    )


def _map_from_text(
    *,
    platform: Platform,
    operation: str,
    implementation: str,
    text: str,
    guard_hints: dict[str, Any] | None = None,
) -> CrawlFailureSignal:
    failure_class = _classify_text(text)
    return _base_signal(
        platform=platform,
        operation=operation,
        implementation=implementation,
        failure_class=failure_class,
        message=text or "操作失败",
        guard_hints=guard_hints,
    )


def sanitize_body_excerpt(text: str, *, limit: int = 2000) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\d{11,}", "***", text)
    return cleaned[:limit]
