from __future__ import annotations

import pytest

from app.platforms.douyin.standalone_keyword_browse import (
    CAPTURE_METHOD,
    CAPTURE_METHOD_PROFILE,
    CAPTURE_METHOD_VIDEO,
    StandaloneKeywordBrowseConfig,
    build_standalone_browse_config,
    capture_method_for_mode,
    resolve_standalone_acquisition_mode,
    validate_standalone_config,
    _is_search_list_ready,
    _keyword_matches_comment,
    _match_comment,
    _on_search_results_url,
    _sync_search_aweme_ids_from_api,
    _take_unique_comments,
)


def test_capture_method_constant():
    assert CAPTURE_METHOD == "standalone_keyword_browse"
    assert capture_method_for_mode("single_video") == CAPTURE_METHOD_VIDEO
    assert capture_method_for_mode("account_home") == CAPTURE_METHOD_PROFILE


def test_validate_standalone_config_modes():
    ok, _ = validate_standalone_config(StandaloneKeywordBrowseConfig(keyword="AI获客"))
    assert ok
    ok, err = validate_standalone_config(
        StandaloneKeywordBrowseConfig(acquisition_mode="single_video")
    )
    assert not ok and "video_url" in err
    ok, err = validate_standalone_config(
        StandaloneKeywordBrowseConfig(
            acquisition_mode="account_home",
            profile_url="https://www.douyin.com/user/MS4wLjABAAAAtest",
        )
    )
    assert ok


def test_resolve_standalone_acquisition_mode_from_video_url():
    mode, video, profile = resolve_standalone_acquisition_mode(
        acquisition_mode="single_video",
        input_url="https://www.douyin.com/video/7123456789012345678",
    )
    assert mode == "single_video"
    assert "7123456789012345678" in video
    assert profile == ""


def test_build_standalone_browse_config_profile_mode():
    cfg = build_standalone_browse_config(
        acquisition_mode="account_home",
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAtest",
        target_precise_leads=2,
        max_videos_to_browse=5,
    )
    assert cfg.acquisition_mode == "account_home"
    assert cfg.target_precise_leads == 2
    assert cfg.max_videos_to_browse == 5


def test_keyword_matches_comment_manual_without_keyword():
    config = StandaloneKeywordBrowseConfig(
        acquisition_mode="single_video",
        video_url="https://www.douyin.com/video/1",
        match_keywords=["报价"],
        min_comment_length=2,
    )
    assert _keyword_matches_comment(config, "淋浴房报价多少")
    assert not _keyword_matches_comment(config, "随便看看")


def test_keyword_matches_comment_uses_search_keyword_by_default():
    config = StandaloneKeywordBrowseConfig(keyword="淋浴房", min_comment_length=2)
    assert _keyword_matches_comment(config, "我家淋浴房漏水怎么办")
    assert not _keyword_matches_comment(config, "招聘销售")


def test_keyword_matches_with_exclude():
    config = StandaloneKeywordBrowseConfig(
        keyword="淋浴房",
        match_keywords=["报价", "多少钱"],
        exclude_keywords=["招聘"],
        min_comment_length=2,
    )
    assert _keyword_matches_comment(config, "淋浴房报价多少")
    assert not _keyword_matches_comment(config, "招聘淋浴房安装工")


def test_action_policy_defaults():
    config = StandaloneKeywordBrowseConfig(keyword="test")
    assert config.action_policy["comment_ratio"] == 50
    assert config.action_policy["dm_ratio"] == 30
    assert config.action_policy["follow_ratio"] == 20
    assert config.reuse_stable_session is True
    assert config.close_browser_after is False


def test_take_unique_comments_dedupes_across_batches():
    seen: set[str] = set()
    batch1 = [{"comment_id": "1", "comment": "a"}, {"comment_id": "2", "comment": "b"}]
    batch2 = [{"comment_id": "1", "comment": "a"}, {"comment_id": "3", "comment": "c"}]
    u1, s1 = _take_unique_comments(batch1, seen)
    u2, s2 = _take_unique_comments(batch2, seen)
    assert [r["comment_id"] for r in u1] == ["1", "2"]
    assert s1 == 0
    assert [r["comment_id"] for r in u2] == ["3"]
    assert s2 == 1


def test_on_search_results_url_accepts_jingxuan_search():
    assert _on_search_results_url("https://www.douyin.com/jingxuan/search/AI%E8%8E%B7%E5%AE%A2?type=general")
    assert not _on_search_results_url("https://www.douyin.com/jingxuan")


def test_sync_search_aweme_ids_from_api():
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

    params = parse_ui_flow_params({"keyword": "AI获客", "content_limit": 3}, platform="douyin")
    ctx = DouyinUiSession(
        settings=None,  # type: ignore[arg-type]
        tenant_id="default",
        account_id="default",
        params=params,
        page=None,  # type: ignore[arg-type]
    )
    api_items = {
        "111": {"aweme_id": "111", "title": "AI获客工具", "digg_count": 10},
        "222": {"aweme_id": "222", "title": "其它", "digg_count": 5},
    }
    ids = _sync_search_aweme_ids_from_api(ctx, api_items)
    assert ids[0] == "111"
    assert ctx.state["search_poster_mode"] is True


@pytest.mark.asyncio
async def test_is_search_list_ready_with_api_items():
    class _Page:
        url = "https://www.douyin.com/jingxuan/search/test?type=general"

    assert await _is_search_list_ready(_Page(), {"1": {"aweme_id": "1"}}) is True
    assert await _is_search_list_ready(_Page(), {}) is False


@pytest.mark.asyncio
async def test_is_search_list_ready_with_api_complete_state():
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

    class _Page:
        url = "https://www.douyin.com/jingxuan/search/test?type=general"

    params = parse_ui_flow_params({"keyword": "AI获客", "content_limit": 3}, platform="douyin")
    ctx = DouyinUiSession(
        settings=None,  # type: ignore[arg-type]
        tenant_id="default",
        account_id="default",
        params=params,
        page=None,  # type: ignore[arg-type]
    )
    ctx.state["search_api_complete"] = True
    ctx.state["search_api_complete_reason"] = "items=2"
    assert await _is_search_list_ready(_Page(), {}, ctx=ctx) is True


@pytest.mark.asyncio
async def test_emit_crawl_progress_throttles_duplicate_messages():
    from app.platforms.douyin.standalone_keyword_browse import _emit_crawl_progress
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

    events: list[tuple[str, dict]] = []

    def on_progress(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    params = parse_ui_flow_params({"keyword": "健身", "content_limit": 3}, platform="douyin")
    ctx = DouyinUiSession(
        settings=None,  # type: ignore[arg-type]
        tenant_id="default",
        account_id="default",
        params=params,
        page=None,  # type: ignore[arg-type]
    )
    ctx.state["_on_progress"] = on_progress

    await _emit_crawl_progress(ctx, "步骤 2/7：搜索关键词", sub="健身", force=True)
    await _emit_crawl_progress(ctx, "步骤 2/7：搜索关键词", sub="健身")
    await _emit_crawl_progress(ctx, "步骤 6/7：滚动评论", sub="第 4 轮", force=True)

    assert len(events) == 2
    assert events[0][0] == "crawl_progress"
    assert events[0][1]["phase"] == "步骤 2/7：搜索关键词"
    assert events[1][1]["phase"] == "步骤 6/7：滚动评论"


def test_crawl_progress_label():
    from app.services.agent_async_job_service import AgentAsyncJobService

    label = AgentAsyncJobService._progress_label(
        "crawl_progress",
        {"phase": "步骤 4/7：浏览视频 6", "sub": "精准线索 1/5"},
    )
    assert label == "步骤 4/7：浏览视频 6 · 精准线索 1/5"
