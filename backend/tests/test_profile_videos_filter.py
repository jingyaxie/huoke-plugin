from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.platforms.douyin.profile_videos import _filter_by_publish_days


def test_filter_by_publish_days_keeps_recent_only():
    now = datetime.now(timezone.utc)
    items = [
        {"aweme_id": "1", "create_time": int((now - timedelta(days=2)).timestamp())},
        {"aweme_id": "2", "create_time": int((now - timedelta(days=10)).timestamp())},
        {"aweme_id": "3", "create_time": None},
    ]
    filtered = _filter_by_publish_days(items, 7)
    assert [row["aweme_id"] for row in filtered] == ["1"]


def test_filter_by_publish_days_uses_calendar_day_cutoff():
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    items = [
        {"aweme_id": "1", "create_time": int((today_start - timedelta(days=7, hours=-1)).timestamp())},
        {"aweme_id": "2", "create_time": int((today_start - timedelta(days=8)).timestamp())},
    ]
    filtered = _filter_by_publish_days(items, 7)
    assert [row["aweme_id"] for row in filtered] == ["1"]
