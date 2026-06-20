from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page

from app.core.config import Settings
from app.services.ui_flow.params import UiFlowParams


@dataclass
class UiStepResult:
    ok: bool
    error: str = ""
    diagnostic: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DouyinUiSession:
    """抖音页面 UI 操作会话（bootstrap / 确定性引导专用，非状态机）。"""

    settings: Settings
    tenant_id: str
    account_id: str
    params: UiFlowParams
    page: Page
    video_urls: list[str] = field(default_factory=list)
    browse_index: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    phase_log: list[str] = field(default_factory=list)
    experience: Any = None
