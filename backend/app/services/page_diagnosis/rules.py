from __future__ import annotations

from app.services.page_diagnosis.contracts import CrawlFailureSignal, IssueType, PageDiagnosis, PageSnapshot
from app.services.page_diagnosis.failure_mapping import issue_type_for
from app.services.page_diagnosis.guidance import ISSUE_LABEL, PLATFORM_LABEL, resolve_guidance


def rule_prefilter(
    signal: CrawlFailureSignal,
    snapshot: PageSnapshot | None,
) -> PageDiagnosis | None:
    hints = dict(signal.guard_hints or {})
    probe = dict(snapshot.guard_probe if snapshot else {})
    merged = {**probe, **hints}

    issue_type: IssueType | None = None
    confidence = 0.0
    evidence: list[str] = []

    if merged.get("automation_blocked"):
        issue_type = "automation_blocked"
        confidence = 0.96
        evidence.append("检测到自动化/拦截页面")
    elif merged.get("captcha"):
        issue_type = "captcha_required"
        confidence = 0.94
        evidence.append("检测到验证码/人机验证页面")
    elif merged.get("guest_mode"):
        issue_type = "login_required"
        confidence = 0.92
        evidence.append("检测到游客态或未登录")
    elif merged.get("login_wall"):
        issue_type = "login_required"
        confidence = 0.90
        evidence.append("检测到登录墙/登录入口")
    elif merged.get("session_valid") is False:
        issue_type = "login_expired"
        confidence = 0.88
        evidence.append("登录 Cookie 无效或缺失")
    elif merged.get("rate_limited") or signal.failure_class == "risk_limit":
        issue_type = "risk_control"
        confidence = 0.85
        evidence.append("触发频率限制或风控信号")
    elif signal.failure_class in {"auth_required", "auth_expired", "captcha", "risk_limit", "automation_blocked"}:
        issue_type = issue_type_for(signal.failure_class)
        confidence = 0.82
        if signal.message:
            evidence.append(signal.message[:120])

    if issue_type is None or confidence < 0.80:
        return None

    guidance = resolve_guidance(signal.platform, issue_type)
    title = guidance.user_title
    if signal.platform in PLATFORM_LABEL and issue_type in ISSUE_LABEL:
        title = f"{PLATFORM_LABEL[signal.platform]}：{guidance.user_title}"

    return PageDiagnosis(
        issue_type=issue_type,
        confidence=confidence,
        user_title=title,
        user_summary=guidance.user_summary,
        user_steps=list(guidance.user_steps),
        can_auto_retry=guidance.can_auto_retry,
        retry_after_seconds=guidance.retry_after_seconds,
        evidence=evidence,
        technical_detail=signal.message or None,
        source="rule",
        platform=signal.platform,
        failure_class=signal.failure_class,
        screenshot_ref=snapshot.screenshot_ref if snapshot else None,
    )


def fallback_diagnosis(signal: CrawlFailureSignal, snapshot: PageSnapshot | None) -> PageDiagnosis:
    issue_type = issue_type_for(signal.failure_class)
    guidance = resolve_guidance(signal.platform, issue_type)
    evidence = [signal.message[:160]] if signal.message else []
    if snapshot and snapshot.title:
        evidence.append(f"页面标题：{snapshot.title[:80]}")
    return PageDiagnosis(
        issue_type=issue_type,
        confidence=0.65,
        user_title=guidance.user_title,
        user_summary=guidance.user_summary,
        user_steps=list(guidance.user_steps),
        can_auto_retry=guidance.can_auto_retry,
        retry_after_seconds=guidance.retry_after_seconds,
        evidence=evidence,
        technical_detail=signal.message or None,
        source="fallback",
        platform=signal.platform,
        failure_class=signal.failure_class,
        screenshot_ref=snapshot.screenshot_ref if snapshot else None,
    )
