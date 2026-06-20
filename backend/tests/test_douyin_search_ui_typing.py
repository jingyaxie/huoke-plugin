from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ui_flow.platforms.douyin.search_ui import (
    _ensure_search_input_keyword,
    _human_type_one_per_second,
    _submit_search,
)


@pytest.mark.asyncio
async def test_human_type_system_chrome_uses_fill_not_press_sequentially():
    """系统 Chrome 下用 fill 写入，避免逐字 press 后误清空。"""
    page = MagicMock()
    search_input = AsyncMock()
    search_input.press_sequentially = AsyncMock()
    ctx = MagicMock()
    ctx.page = page
    ctx.settings = MagicMock()
    ctx.tenant_id = "default"

    with (
        patch("app.core.antibot.antibot_suppressed_for_page", return_value=True),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._activate_searchbar",
            new=AsyncMock(),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._read_search_input_value",
            new=AsyncMock(side_effect=["", "淋浴房"]),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._clear_search_input",
            new=AsyncMock(),
        ) as clear_input,
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui.human_type",
            new=AsyncMock(),
        ) as human_type,
    ):
        await _human_type_one_per_second(ctx, search_input, "淋浴房")

    human_type.assert_awaited()
    search_input.press_sequentially.assert_not_called()
    # 校验失败时不应再次 clear（旧逻辑会误删用户可见的关键词）
    assert clear_input.await_count == 1


@pytest.mark.asyncio
async def test_ensure_search_input_keyword_skips_clear_when_already_correct():
    ctx = MagicMock()
    ctx.settings = MagicMock()
    ctx.tenant_id = "default"
    search_input = AsyncMock()

    with (
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._read_search_input_value",
            new=AsyncMock(return_value="淋浴房"),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui.human_type",
            new=AsyncMock(),
        ) as human_type,
    ):
        ok = await _ensure_search_input_keyword(ctx, search_input, "淋浴房")

    assert ok is True
    human_type.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_search_marks_submitted_only_after_navigation():
    btn = MagicMock()
    btn.count = AsyncMock(return_value=0)
    btn.is_visible = AsyncMock(return_value=False)
    search_input = MagicMock()
    search_input.count = AsyncMock(return_value=1)
    search_input.focus = AsyncMock()

    btn_locator = MagicMock()
    btn_locator.first = btn

    page = MagicMock()
    page.url = "https://www.douyin.com/jingxuan"
    page.locator = MagicMock(return_value=btn_locator)
    page.get_by_role.return_value.first.count = AsyncMock(return_value=0)
    page.get_by_role.return_value.first.is_visible = AsyncMock(return_value=False)
    page.keyboard.press = AsyncMock()

    ctx = MagicMock()
    ctx.page = page
    ctx.settings = MagicMock()
    ctx.tenant_id = "default"
    ctx.state = {}
    ctx.experience = None
    ctx.params = MagicMock(keyword="淋浴房")

    async def _set_search_url(*_args, **_kwargs):
        page.url = "https://www.douyin.com/jingxuan/search/淋浴房?type=general"

    page.keyboard.press.side_effect = _set_search_url

    with (
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._search_input_locator",
            new=AsyncMock(return_value=search_input),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._ensure_search_input_keyword",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui.human_click",
            new=AsyncMock(),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui.release_searchbar_focus",
            new=AsyncMock(),
        ),
    ):
        await _submit_search(ctx, keyword="淋浴房")

    assert ctx.state["search_submitted"] is True
