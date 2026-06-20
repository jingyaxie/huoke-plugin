from __future__ import annotations

from app.services.page_understanding import infer_page_context


def test_modal_feed_without_panel_hints_click_comment_icon():
    ctx = infer_page_context(
        url="https://www.douyin.com/search/快餐?modal_id=7123456789",
        title="抖音",
        interactive_elements=[{"text": "35", "tag": "span", "selector_hint": ""}],
        overlays=[],
    )
    assert ctx["scene"] == "feed_with_comments"
    hints = " ".join(ctx["hints"])
    assert "Space" in hints or "暂停" in hints
    assert "feed-comment-icon" in hints


def test_modal_id_url_detected_as_feed_with_comments():
    ctx = infer_page_context(
        url="https://www.douyin.com/search/团餐?modal_id=7123456789",
        title="抖音搜索",
        interactive_elements=[],
        overlays=[{"label": "筛选", "controls": [{"text": "一周内", "tag": "button"}]}],
    )
    assert ctx["scene"] == "feed_with_comments"


def test_video_url_detected_as_feed():
    ctx = infer_page_context(
        url="https://www.douyin.com/video/7123456789",
        title="抖音",
        interactive_elements=[],
        overlays=[],
    )
    assert ctx["scene"] == "feed_with_comments"
