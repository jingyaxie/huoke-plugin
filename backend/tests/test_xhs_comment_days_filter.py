from __future__ import annotations

import time

from app.platforms.xiaohongshu.comments import _apply_comment_days_filter


def _comment(comment_id: str, age_days: int) -> dict:
    return {
        "comment_id": comment_id,
        "create_time": int(time.time()) - age_days * 86400,
    }


def test_apply_comment_days_filter_keeps_recent_only():
    payload = {
        "comments": [_comment("new", 1), _comment("old", 30)],
        "api_total_top_comments": 2,
    }
    _apply_comment_days_filter(payload, 7, max_comments=50)
    ids = {row["comment_id"] for row in payload["comments"]}
    assert ids == {"new"}
    assert payload["comment_days"] == 7
    assert payload["total_comments_captured"] == 1


def test_apply_comment_days_filter_sets_warning_when_all_filtered():
    payload = {
        "comments": [_comment("old", 30)],
        "api_total_top_comments": 5,
    }
    _apply_comment_days_filter(payload, 3, max_comments=50)
    assert payload["comments"] == []
    assert "近 3 天" in (payload.get("warning") or "")


def test_apply_comment_days_filter_noop_when_none():
    payload = {"comments": [_comment("old", 30)], "api_total_top_comments": 1}
    _apply_comment_days_filter(payload, None, max_comments=50)
    assert len(payload["comments"]) == 1
    assert "comment_days" not in payload
