from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Platform = Literal["douyin", "xiaohongshu", "kuaishou"]

FailureClass = Literal[
    "auth_required",
    "auth_expired",
    "captcha",
    "risk_limit",
    "automation_blocked",
    "page_structure",
    "empty_result",
    "network",
    "internal",
    "unknown",
]

IssueType = Literal[
    "login_required",
    "login_expired",
    "captcha_required",
    "risk_control",
    "automation_blocked",
    "page_changed",
    "empty_data",
    "network_error",
    "internal_error",
    "unknown",
]


class CrawlFailureSignal(BaseModel):
    platform: Platform
    operation: str
    implementation: str = "unknown"
    failure_class: FailureClass
    message: str = ""
    recoverable: bool = False
    page_available: bool = False
    guard_hints: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class PageSnapshot(BaseModel):
    platform: Platform
    url: str | None = None
    title: str | None = None
    scene: str | None = None
    body_excerpt: str | None = None
    interactive_summary: list[dict[str, Any]] = Field(default_factory=list)
    overlays: list[dict[str, Any]] = Field(default_factory=list)
    guard_probe: dict[str, Any] = Field(default_factory=dict)
    screenshot_ref: str | None = None
    collected_via: str = "none"


class PageDiagnosis(BaseModel):
    issue_type: IssueType
    confidence: float = 0.0
    user_title: str
    user_summary: str = ""
    user_steps: list[str] = Field(default_factory=list)
    can_auto_retry: bool = True
    retry_after_seconds: int | None = None
    evidence: list[str] = Field(default_factory=list)
    technical_detail: str | None = None
    source: Literal["rule", "llm", "fallback"] = "rule"
    platform: Platform
    failure_class: FailureClass
    screenshot_ref: str | None = None
