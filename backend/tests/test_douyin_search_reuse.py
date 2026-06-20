from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ui_flow.params import parse_ui_flow_params
from app.services.ui_flow.platforms.douyin.prepare_ui import run_prepare
from app.services.ui_flow.platforms.douyin.search_ui import (
    page_ready_for_search_reuse,
    reuse_search_results_if_ready,
)
from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession, UiStepResult


def _make_ctx(*, keyword: str = "健身", reuse: bool = False) -> DouyinUiSession:
    params = parse_ui_flow_params(
        {"keyword": keyword, "content_limit": 5, "ui_search_only": True},
        platform="douyin",
    )
    page = MagicMock()
    page.url = f"https://www.douyin.com/jingxuan/search/{keyword}?type=general"
    page.bring_to_front = AsyncMock()
    page.goto = AsyncMock()
    ctx = DouyinUiSession(
        settings=MagicMock(),
        tenant_id="default",
        account_id="default",
        params=params,
        page=page,
    )
    if reuse:
        ctx.state["reuse_search_session"] = True
    return ctx


@pytest.mark.asyncio
async def test_page_ready_for_search_reuse_when_on_matching_results():
    ctx = _make_ctx()
    with (
        patch(
            "app.platforms.douyin.human_guards.is_captcha_page",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.feed_ui.feed_overlay_visible",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._read_search_input_value",
            new=AsyncMock(return_value="健身"),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._search_page_has_results",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert await page_ready_for_search_reuse(ctx) is True


@pytest.mark.asyncio
async def test_page_ready_for_search_reuse_false_on_feed_overlay():
    ctx = _make_ctx()
    with (
        patch(
            "app.platforms.douyin.human_guards.is_captcha_page",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.feed_ui.feed_overlay_visible",
            new=AsyncMock(return_value=True),
        ),
    ):
        assert await page_ready_for_search_reuse(ctx) is False


@pytest.mark.asyncio
async def test_reuse_search_results_if_ready_skips_resubmit():
    ctx = _make_ctx(reuse=True)
    ok_result = UiStepResult(ok=True, data={"video_urls": ["https://example.com/v/1"]})

    with (
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui.page_ready_for_search_reuse",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._finalize_search_success",
            new=AsyncMock(return_value=ok_result),
        ) as finalize,
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui._needs_ui_publish_filter",
            return_value=False,
        ),
    ):
        result = await reuse_search_results_if_ready(ctx, limit=5)

    assert result is not None and result.ok
    finalize.assert_awaited_once()
    assert ctx.state["search_submitted"] is True
    assert "search_ui_reuse" in str(finalize.await_args.kwargs.get("capture_method", ""))


@pytest.mark.asyncio
async def test_run_prepare_skips_goto_when_reuse_session_ready():
    ctx = _make_ctx(reuse=True)
    with (
        patch(
            "app.services.ui_flow.platforms.douyin.search_ui.page_ready_for_search_reuse",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.platforms.douyin.human_guards.is_captcha_page",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await run_prepare(ctx)

    assert result.ok
    assert result.data.get("reused_search") is True
    ctx.page.goto.assert_not_awaited()


@pytest.mark.asyncio
async def test_attempt_search_reuse_short_circuits_search_phase():
    from app.platforms.douyin.standalone_keyword_browse import (
        StandaloneKeywordBrowseConfig,
        _attempt_search_reuse,
        _build_ui_session,
    )

    config = StandaloneKeywordBrowseConfig(keyword="健身", content_limit=5)
    page = MagicMock()
    page.url = "https://www.douyin.com/jingxuan/search/健身?type=general"
    ctx = _build_ui_session(
        page,
        MagicMock(),
        tenant_id="default",
        account_id="default",
        config=config,
    )
    ctx.state["reuse_search_session"] = True

    reused_result = UiStepResult(ok=True, diagnostic="复用当前搜索页")

    with (
        patch(
            "app.platforms.douyin.standalone_keyword_browse._on_search_results_url",
            return_value=True,
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse.feed_overlay_visible",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse.reuse_search_results_if_ready",
            new=AsyncMock(return_value=reused_result),
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse._sync_search_aweme_ids_from_api",
            return_value=["111"],
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse._report_step",
            new=AsyncMock(),
        ),
    ):
        reused, diag = await _attempt_search_reuse(ctx, config)

    assert reused is True
    assert "复用" in diag
