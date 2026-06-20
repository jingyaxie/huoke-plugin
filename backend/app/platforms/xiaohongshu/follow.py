"""小红书关注常量（Direct API 已移除，关注请走 warm_outreach）。"""

from __future__ import annotations

_FOLLOWED_LABELS = ("已关注", "互相关注", "发消息")


def _parse_follow_status(user: dict) -> str:
    if not isinstance(user, dict):
        return "unknown"
    for key in ("followed", "is_followed", "follow_status"):
        value = user.get(key)
        if value is True or value in {1, "1", "followed", "follows"}:
            return "followed"
        if value is False or value in {0, "0", "none"}:
            return "none"
    return str(user.get("follow_status") or "unknown")
