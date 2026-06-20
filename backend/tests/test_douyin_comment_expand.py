from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ui_flow.platforms.douyin.feed_ui import (
    _REPLY_EXPAND_SELECTORS,
    expand_replies_for_parent_comment,
    scroll_comment_sidebar_until,
)


def test_reply_expand_selectors_not_empty():
    assert any("条回复" in s for s in _REPLY_EXPAND_SELECTORS)


@pytest.mark.asyncio
async def test_expand_replies_clicks_visible_expand_button():
    page = MagicMock()
    settings = MagicMock()
    parent = MagicMock()
    loc = MagicMock()
    loc.count = AsyncMock(return_value=1)
    loc.is_visible = AsyncMock(return_value=True)
    parent.locator.return_value.first = loc
    parent.scroll_into_view_if_needed = AsyncMock()

    from app.services.ui_flow.platforms import douyin as douyin_pkg

    feed_ui = douyin_pkg.feed_ui
    feed_ui.human_click = AsyncMock()
    feed_ui.human_delay = AsyncMock()

    ok = await expand_replies_for_parent_comment(
        page,
        settings,
        tenant_id="default",
        parent_item=parent,
        max_clicks=1,
    )
    assert ok is True
    feed_ui.human_click.assert_awaited()


@pytest.mark.asyncio
async def test_scroll_comment_sidebar_expands_parent_before_child():
    page = MagicMock()
    settings = MagicMock()
    calls: list[str] = []

    async def fake_find(page, *, comment_id="", comment_text=""):
        if comment_id == "parent1":
            calls.append("find_parent")
            return MagicMock(name="parent")
        if comment_id == "child1":
            calls.append("find_child")
            return MagicMock(name="child") if "expand" in calls else None
        return None

    from app.services.ui_flow.platforms import douyin as douyin_pkg

    feed_ui = douyin_pkg.feed_ui
    feed_ui.activate_comment_sidebar_on_page = AsyncMock(return_value=True)
    feed_ui.find_comment_item_locator = fake_find
    feed_ui.expand_replies_for_parent_comment = AsyncMock(
        side_effect=lambda *a, **k: calls.append("expand") or True
    )
    feed_ui.scroll_comment_sidebar_on_page = AsyncMock()

    target = await scroll_comment_sidebar_until(
        page,
        settings,
        tenant_id="default",
        comment_id="child1",
        parent_comment_id="parent1",
        max_rounds=2,
    )
    assert target is not None
    assert "find_parent" in calls
    assert "expand" in calls
    assert "find_child" in calls
