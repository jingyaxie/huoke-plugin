from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platforms.xiaohongshu.search import XhsSearchTool


@pytest.mark.asyncio
async def test_xhs_keyword_search_never_goto_search_url():
    """小红书关键词搜索必须走搜索框，禁止 page.goto(search_result?keyword=...)。"""
    settings = MagicMock()
    settings.xhs_explore_url = "https://www.xiaohongshu.com/explore"
    settings.xhs_home_url = "https://www.xiaohongshu.com"
    settings.report_output_dir = MagicMock()

    store = MagicMock()
    tool = XhsSearchTool(settings, "default", store, account_id="default")

    page = AsyncMock()
    page.url = "https://www.xiaohongshu.com/search_result_ai?keyword=test"
    page.wait_for_timeout = AsyncMock()
    page.on = MagicMock()
    page.remove_listener = MagicMock()

    goto_calls: list[str] = []

    async def _goto(url, **kwargs):
        goto_calls.append(str(url))

    page.goto = _goto

    with (
        patch.object(tool, "_ensure_feeds_top_search", AsyncMock(return_value=True)),
        patch.object(tool, "_trigger_searchbar", AsyncMock(return_value=True)),
        patch.object(tool, "_maybe_apply_search_publish_filter", AsyncMock(return_value=None)),
        patch.object(tool, "_collect_search_results_on_page", AsyncMock(return_value=(["https://x"], "ok"))),
    ):
        urls, _ = await tool._thin_browser_keyword_search(
            page,
            keyword="团餐",
            limit=1,
            captured_api_urls=[],
        )

    assert urls
    assert not any("search_result" in u and "keyword=" in u for u in goto_calls)


@pytest.mark.asyncio
async def test_xhs_search_notes_from_existing_page_uses_searchbar():
    settings = MagicMock()
    store = MagicMock()
    tool = XhsSearchTool(settings, "default", store, account_id="default")
    page = AsyncMock()

    with patch.object(
        tool,
        "_ui_searchbar_keyword_search",
        AsyncMock(return_value=(["https://x"], "searchbar")),
    ) as mocked:
        urls, diag = await tool.search_notes_from_existing_page(page, "团餐", 1)

    mocked.assert_awaited_once()
    assert urls == ["https://x"]
    assert diag == "searchbar"
