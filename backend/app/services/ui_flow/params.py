from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.platforms.types import normalize_platform


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _default_comment_match() -> dict[str, Any]:
    return {
        "mode": "keyword",
        "keywords": ["多少钱", "报价", "怎么收费", "价格"],
        "min_comment_length": 4,
    }


@dataclass
class UiFlowParams:
    platform: str = "douyin"
    keyword: str = ""
    content_limit: int = 3
    days: int = 7
    region: str | None = None
    comment_match: dict[str, Any] = field(default_factory=dict)
    follow_match: dict[str, Any] | None = None
    actions_on_match: list[dict[str, Any]] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    ui_timing: dict[str, Any] = field(default_factory=dict)
    platform_options: dict[str, Any] = field(default_factory=dict)
    skip_search_filter: bool = False
    inline_ui_outreach: bool = False
    ui_search_only: bool = False
    dry_run: bool = False
    show_browser: bool = True
    force_refresh: bool = True
    persist_to_db: bool = True
    task_id: str | None = None

    @property
    def max_comments_per_video(self) -> int:
        return int(self.limits.get("max_comments_per_video") or 50)

    @property
    def max_replies(self) -> int:
        return int(self.limits.get("max_replies") or 5)

    @property
    def max_follows(self) -> int:
        return int(self.limits.get("max_follows") or 3)

    @property
    def max_comments_scanned(self) -> int:
        return int(self.limits.get("max_comments_scanned") or 200)

    @property
    def dedupe_user_per_task(self) -> bool:
        return bool(self.limits.get("dedupe_user_per_task", True))

    @property
    def watch_seconds_min(self) -> int:
        return int(self.ui_timing.get("watch_seconds_min") or 5)

    @property
    def watch_seconds_max(self) -> int:
        return int(self.ui_timing.get("watch_seconds_max") or 12)

    @property
    def scroll_rounds_per_video(self) -> int:
        return int(self.ui_timing.get("scroll_rounds_per_video") or 4)

    @property
    def interval_min_sec(self) -> int:
        return int(self.ui_timing.get("interval_min_sec") or 30)

    @property
    def interval_max_sec(self) -> int:
        return int(self.ui_timing.get("interval_max_sec") or 120)

    @property
    def entry(self) -> str:
        return str(self.platform_options.get("entry") or "home")


def parse_ui_flow_params(raw: dict[str, Any], *, platform: str) -> UiFlowParams:
    keyword = str(raw.get("keyword") or raw.get("search_keyword") or "").strip()
    comment_match = _maybe_json(raw.get("comment_match"))
    comment_match = comment_match if isinstance(comment_match, dict) else _default_comment_match()
    follow_raw = _maybe_json(raw.get("follow_match"))
    follow_match = follow_raw if isinstance(follow_raw, dict) else None
    actions = _maybe_json(raw.get("actions_on_match"))
    actions = actions if isinstance(actions, list) else []
    limits = _maybe_json(raw.get("limits"))
    limits = limits if isinstance(limits, dict) else {}
    ui_timing = _maybe_json(raw.get("ui_timing"))
    ui_timing = ui_timing if isinstance(ui_timing, dict) else {}
    platform_options = _maybe_json(raw.get("platform_options"))
    platform_options = platform_options if isinstance(platform_options, dict) else {}

    content_limit = raw.get("crawl_video_limit")
    if content_limit is None:
        content_limit = raw.get("content_limit")
    if content_limit is None:
        content_limit = raw.get("limit") or raw.get("video_limit") or raw.get("video_limit_per_batch")
    show_browser = raw.get("show_browser")
    if show_browser is None:
        show_browser = True

    return UiFlowParams(
        platform=normalize_platform(str(raw.get("platform") or platform)),
        keyword=keyword,
        content_limit=max(1, int(content_limit or 5)),
        days=int(raw.get("days") or 7),
        region=raw.get("region"),
        comment_match=comment_match,
        follow_match=follow_match,
        actions_on_match=actions,
        limits=limits,
        ui_timing=ui_timing,
        platform_options=platform_options,
        skip_search_filter=bool(raw.get("skip_search_filter", False)),
        inline_ui_outreach=bool(raw.get("inline_ui_outreach", False)),
        ui_search_only=bool(raw.get("ui_search_only", False)),
        dry_run=bool(raw.get("dry_run", False)),
        show_browser=bool(show_browser),
        force_refresh=bool(raw.get("force_refresh", True)),
        persist_to_db=bool(raw.get("persist_to_db", True)),
        task_id=raw.get("task_id"),
    )
