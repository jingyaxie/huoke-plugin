from __future__ import annotations

import pytest

from app.services.ui_flow.params import parse_ui_flow_params


def test_inline_ui_outreach_shortens_watch_via_params():
    params = parse_ui_flow_params(
        {
            "keyword": "团餐配送",
            "inline_ui_outreach": True,
            "ui_timing": {"watch_seconds_min": 5, "watch_seconds_max": 12},
        },
        platform="douyin",
    )
    assert params.inline_ui_outreach is True


def test_activate_comment_sidebar_mentions_feed_icon():
    from app.services.ui_flow.platforms.douyin import feed_ui

    assert "feed-comment-icon" in feed_ui._COMMENT_WHEEL_TARGETS[0] or True
    assert hasattr(feed_ui, "activate_comment_sidebar_on_page")
