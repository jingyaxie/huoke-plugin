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


@dataclass
class SocialRoamParams:
    platform: str = "douyin"
    keyword: str = ""
    browse_mode: str = "keyword"
    content_limit: int = 10
    days: int = 3
    region: str | None = None
    comment_match: dict[str, Any] = field(default_factory=dict)
    follow_match: dict[str, Any] | None = None
    actions_on_match: list[dict[str, Any]] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)
    human_simulation: dict[str, Any] = field(default_factory=dict)
    collect: dict[str, Any] = field(default_factory=dict)
    show_browser: bool = True
    dry_run: bool = False
    task_id: str | None = None

    @property
    def max_replies(self) -> int:
        return int(self.limits.get("max_replies") or 5)

    @property
    def max_follows(self) -> int:
        return int(self.limits.get("max_follows") or 3)

    @property
    def max_comments_scanned(self) -> int:
        return int(self.limits.get("max_comments_scanned") or 300)

    @property
    def dedupe_user_per_task(self) -> bool:
        return bool(self.limits.get("dedupe_user_per_task", True))

    @property
    def min_seconds_between_writes(self) -> float:
        return float(self.human_simulation.get("min_seconds_between_writes") or 8)

    @property
    def interval_min_sec(self) -> int:
        return int(self.human_simulation.get("interval_min_sec") or self.min_seconds_between_writes)

    @property
    def interval_max_sec(self) -> int:
        return int(
            self.human_simulation.get("interval_max_sec")
            or max(self.interval_min_sec, int(self.min_seconds_between_writes * 2))
        )

    @property
    def persist_to_db(self) -> bool:
        return bool(self.collect.get("persist_to_db", True))


def _default_comment_match() -> dict[str, Any]:
    return {
        "mode": "keyword",
        "keywords": ["多少钱", "报价", "怎么收费", "价格"],
        "min_comment_length": 4,
    }


def _default_follow_match() -> dict[str, Any]:
    return {
        "mode": "keyword",
        "keywords": ["想装", "求推荐", "怎么联系", "想做"],
    }


def _default_actions() -> list[dict[str, Any]]:
    return [
        {"type": "reply", "template": "您好，可以私信发您案例和报价～"},
        {"type": "follow"},
    ]


def parse_social_roam_params(raw: dict[str, Any], *, platform: str) -> SocialRoamParams:
    browse = raw.get("browse") if isinstance(raw.get("browse"), dict) else {}
    keyword = str(
        raw.get("keyword")
        or browse.get("keyword")
        or raw.get("search_keyword")
        or ""
    ).strip()
    comment_match = _maybe_json(raw.get("comment_match"))
    comment_match = comment_match if isinstance(comment_match, dict) else {}
    follow_raw = _maybe_json(raw.get("follow_match"))
    follow_match = follow_raw if isinstance(follow_raw, dict) else None
    actions = _maybe_json(raw.get("actions_on_match"))
    if not isinstance(actions, list) or not actions:
        actions = _default_actions()
    limits = _maybe_json(raw.get("limits"))
    limits = limits if isinstance(limits, dict) else {}
    human_simulation = _maybe_json(raw.get("human_simulation"))
    human_simulation = human_simulation if isinstance(human_simulation, dict) else {}
    collect = _maybe_json(raw.get("collect"))
    collect = collect if isinstance(collect, dict) else {}
    show_browser = raw.get("show_browser")
    if show_browser is None:
        show_browser = True
    return SocialRoamParams(
        platform=normalize_platform(str(raw.get("platform") or platform)),
        keyword=keyword,
        browse_mode=str(browse.get("mode") or "keyword").strip().lower(),
        content_limit=int(raw.get("content_limit") or raw.get("limit") or 10),
        days=int(raw.get("days") or 3),
        region=str(raw.get("region") or browse.get("region") or "").strip() or None,
        comment_match=comment_match or _default_comment_match(),
        follow_match=follow_match if follow_match else _default_follow_match(),
        actions_on_match=list(actions),
        limits=limits,
        human_simulation={"enabled": True, "delay_profile": "normal", **human_simulation},
        collect={"persist_to_db": True, **collect},
        show_browser=bool(show_browser),
        dry_run=bool(raw.get("dry_run", False)),
        task_id=str(raw.get("task_id") or "").strip() or None,
    )


def render_template(template: str, *, nickname: str, comment: str) -> str:
    text = template or ""
    text = text.replace("{{username}}", nickname).replace("{{nickname}}", nickname)
    text = text.replace("{{comment}}", comment)
    return text.strip()
