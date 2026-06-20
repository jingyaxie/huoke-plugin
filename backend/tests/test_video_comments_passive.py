from __future__ import annotations

from datetime import datetime, timezone

from app.platforms.douyin.video_comments_passive import (
    _days_cutoff_ts,
    _filter_comments_by_days,
    _should_stop_for_time_window,
    comment_scroll_stop_reason,
)


def _cutoff(days: int = 7) -> int:
    return int(_days_cutoff_ts(days) or 0)


def test_should_not_stop_on_first_hot_page_with_old_comments():
    cutoff = _cutoff(7)
    old_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    last_page = {"comments": [{"create_time": old_ts}], "has_more": 1}
    assert not _should_stop_for_time_window(
        cutoff_ts=cutoff,
        round_idx=0,
        filtered_count=0,
        last_page=last_page,
    )


def test_should_stop_after_scroll_when_last_page_is_old_and_has_matches():
    cutoff = _cutoff(7)
    old_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    last_page = {"comments": [{"create_time": old_ts}], "has_more": 0}
    assert _should_stop_for_time_window(
        cutoff_ts=cutoff,
        round_idx=3,
        filtered_count=5,
        last_page=last_page,
    )


def test_should_stop_when_last_page_is_old_even_without_in_window_matches():
    cutoff = _cutoff(7)
    old_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    last_page = {"comments": [{"create_time": old_ts}], "has_more": 1}
    assert _should_stop_for_time_window(
        cutoff_ts=cutoff,
        round_idx=2,
        filtered_count=0,
        last_page=last_page,
    )


def test_should_not_stop_before_min_scroll_rounds():
    cutoff = _cutoff(7)
    old_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
    last_page = {"comments": [{"create_time": old_ts}], "has_more": 1}
    assert not _should_stop_for_time_window(
        cutoff_ts=cutoff,
        round_idx=0,
        filtered_count=0,
        last_page=last_page,
        min_scroll_before_time_stop=2,
    )


def test_comment_scroll_stop_only_on_time_window_or_no_more_pages():
    cutoff = _cutoff(7)
    recent = int(datetime.now(timezone.utc).timestamp())
    pages = [{"comments": [{"create_time": recent}], "has_more": 1}]
    assert comment_scroll_stop_reason(
        cutoff_ts=cutoff,
        round_idx=1,
        last_page=pages[-1],
        captured_pages=pages,
        comment_days=7,
    ) is None

    pages_end = [{"comments": [{"create_time": recent}], "has_more": 0}]
    assert comment_scroll_stop_reason(
        cutoff_ts=cutoff,
        round_idx=2,
        last_page=pages_end[-1],
        captured_pages=pages_end,
        comment_days=7,
    ) == "评论已全部加载（无更多分页）"


def test_filter_keeps_recent_comments_only():
    cutoff = _cutoff(7)
    now = int(datetime.now(timezone.utc).timestamp())
    old = now - 30 * 86400
    comments_map = {
        "1": {"comment_id": "1", "create_time": now, "parent_comment_id": None},
        "2": {"comment_id": "2", "create_time": old, "parent_comment_id": None},
    }
    filtered = _filter_comments_by_days(comments_map, cutoff_ts=cutoff, max_comments=50)
    assert [row["comment_id"] for row in filtered] == ["1"]
