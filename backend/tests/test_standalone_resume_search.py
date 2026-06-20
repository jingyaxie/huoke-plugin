from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platforms.douyin.standalone_keyword_browse import (
    StandaloneKeywordBrowseConfig,
    _attempt_resume_saved_search,
    _build_ui_session,
)
from app.services.standalone_browse_adapter import run_standalone_browse_for_supervisor


@pytest.mark.asyncio
async def test_attempt_resume_saved_search_goto_and_reuse():
    config = StandaloneKeywordBrowseConfig(
        keyword="健身",
        start_video_index=5,
        resume_search_url="https://www.douyin.com/jingxuan/search/健身?type=general",
    )
    page = MagicMock()
    page.url = "about:blank"
    page.bring_to_front = AsyncMock()
    page.goto = AsyncMock()
    ctx = _build_ui_session(
        page,
        MagicMock(),
        tenant_id="default",
        account_id="default",
        config=config,
    )
    ctx.state["reuse_search_session"] = True

    with (
        patch(
            "app.platforms.douyin.standalone_keyword_browse.feed_overlay_visible",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse._wait_captcha_if_needed",
            new=AsyncMock(),
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse.assert_douyin_human_ready",
            new=AsyncMock(return_value={"ok": True}),
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse._attempt_search_reuse",
            new=AsyncMock(return_value=(True, "复用搜索页")),
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse._report_step",
            new=AsyncMock(),
        ),
        patch(
            "app.platforms.douyin.standalone_keyword_browse.human_delay",
            new=AsyncMock(),
        ),
    ):
        ok, diag = await _attempt_resume_saved_search(
            ctx,
            config,
            page=page,
            settings=MagicMock(),
            tenant_id="default",
            account_id="default",
            store=MagicMock(),
            stable_session=MagicMock(stable_mode=True),
        )

    assert ok is True
    page.goto.assert_awaited_once()
    assert ctx.state["search_url"] == config.resume_search_url
    assert "复用" in diag


@pytest.mark.asyncio
async def test_adapter_passes_resume_search_url_from_supervisor_state():
    from app.services.task_brief_service import TaskBrief

    brief = TaskBrief(brief_md="test", keyword="健身", goals={"target_leads": 5})
    state = {
        "standalone_browse_offset": 8,
        "standalone_search_url": "https://www.douyin.com/jingxuan/search/健身?type=general",
    }
    params = {"keyword": "健身", "show_browser": True}

    with patch(
        "app.services.standalone_browse_adapter.brief_to_standalone_config",
    ) as mock_cfg:
        mock_cfg.return_value = MagicMock()
        with patch(
            "app.services.standalone_browse_adapter.run_standalone_keyword_browse_with_browser",
            new=AsyncMock(return_value=MagicMock(
                ok=False,
                keyword="健身",
                acquisition_mode="keyword_auto",
                videos_processed=0,
                comments_scanned=0,
                precise_leads=[],
                phase_log=[],
                target_reached=False,
                search_exhausted=False,
            )),
        ):
            await run_standalone_browse_for_supervisor(
                MagicMock(),
                tenant_id="default",
                account_id="default",
                brief=brief,
                params=params,
                action="crawl_keyword",
                db_session=None,
                state=state,
            )

    call_params = mock_cfg.call_args[0][1]
    assert call_params["start_video_index"] == 8
    assert call_params["resume_search_url"] == state["standalone_search_url"]
