from __future__ import annotations

import re

from app.services.ui_flow.platforms.douyin.feed_ui import extract_comment_total_from_page_text


def test_extract_comment_total():
    assert extract_comment_total_from_page_text("全部评论(561)") == 561
    assert extract_comment_total_from_page_text("全部评论（120）") is None
    assert extract_comment_total_from_page_text("无评论") is None


def test_feed_modal_comment_wheel_targets():
    from app.services.ui_flow.platforms.douyin import feed_ui

    assert feed_ui._FEED_MODAL_COMMENT_ROOT == '[data-e2e="feed-active-video"]'
    assert feed_ui._COMMENT_WHEEL_TARGETS[0].endswith('[data-e2e="comment-item"]')
    assert "feed-active-video" in feed_ui.COMMENT_SIDEBAR_SCROLL_JS
    assert "comment-item" in feed_ui.COMMENT_SIDEBAR_SCROLL_JS
    assert "feed-comment-icon" in feed_ui._CLICK_COMMENT_ICON_JS
