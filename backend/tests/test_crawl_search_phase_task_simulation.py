"""模拟测试：搜索阶段成功但 0 评论时，任务应继续抓取而非挂起。"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import (
    build_supervisor_execution_plan,
    plan_driven_supervisor_decision,
)
from app.services.task_supervisor_service import TaskSupervisorService
from tests.task_execution_simulator import mock_interaction_stats


def _skill_flow_brief(*, platform: str = "douyin", keyword: str = "淋浴房") -> TaskBrief:
    return TaskBrief(
        keyword=keyword,
        platform=platform,
        goals={
            "target_leads": 10,
            "execution_mode": "skill_flow",
            "agent_strategy": f"skill-flow-{platform}",
        },
    )


def _search_phase_partial(*, platform: str = "douyin") -> dict:
    if platform == "xiaohongshu":
        return {
            "status": "partial",
            "platform": platform,
            "keyword": "淋浴房",
            "videos_processed": 0,
            "total_comments_captured": 0,
            "search_succeeded": True,
            "search_url": "https://www.xiaohongshu.com/search_result?keyword=淋浴房",
            "discovered_video_urls": [
                "https://www.xiaohongshu.com/explore/abc123def456",
            ],
            "discovered_video_count": 1,
            "results": [],
        }
    return {
        "status": "partial",
        "platform": platform,
        "keyword": "淋浴房",
        "videos_processed": 0,
        "total_comments_captured": 0,
        "search_succeeded": True,
        "search_url": "https://www.douyin.com/jingxuan/search/淋浴房",
        "discovered_video_urls": [
            "https://www.douyin.com/video/7123456789012345678",
        ],
        "discovered_video_count": 1,
        "results": [],
    }


def _crawl_with_comments(*, platform: str = "douyin", captured: int = 18) -> dict:
    return {
        "status": "completed",
        "platform": platform,
        "keyword": "淋浴房",
        "videos_processed": 2,
        "total_comments_captured": captured,
        "results": [
            {
                "video_url": "https://www.douyin.com/video/7123456789012345678",
                "comments": [{"comment_id": "c1", "comment": "多少钱"}],
            }
        ],
    }


def _simulate_crawl_rounds(
    settings: Settings,
    brief: TaskBrief,
    skill_results: list[dict],
    *,
    dry_run: bool = True,
) -> tuple[list[str], dict]:
    platform = str(brief.platform or "douyin")
    svc = TaskSupervisorService(settings, "default", platform, "default")
    plan = build_supervisor_execution_plan(brief, {})
    state: dict = {"execution_plan": plan, "job_id": "sim-search-phase"}
    stats = mock_interaction_stats(brief)
    actions: list[str] = []

    for skill_result in skill_results:
        decision = plan_driven_supervisor_decision(
            state["execution_plan"],
            brief,
            state,
            stats=stats,
        )
        assert decision is not None, "计划驱动决策不应为空"
        action = str(decision["action"])
        actions.append(action)
        if action != "crawl_keyword":
            break
        svc._update_state(
            state,
            action,
            skill_result,
            brief,
            dry_run=dry_run,
            params=dict(decision.get("params") or {}),
        )
    return actions, state


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "storage")


@pytest.mark.parametrize("platform", ["douyin", "xiaohongshu"])
def test_update_state_search_phase_partial_not_failed(settings, platform):
    brief = _skill_flow_brief(platform=platform)
    plan = build_supervisor_execution_plan(brief, {})
    state = {"execution_plan": plan, "job_id": "sim-job"}
    svc = TaskSupervisorService(settings, "default", platform, "default")

    svc._update_state(
        state,
        "crawl_keyword",
        _search_phase_partial(platform=platform),
        brief,
        dry_run=False,
    )

    assert state.get("crawl_done") is not True
    assert state.get("crawl_failures", 0) == 0
    assert "搜索已成功" in str(state.get("last_crawl_error") or "")
    assert state["execution_plan"]["steps"][0]["status"] == "in_progress"
    assert state["execution_plan"]["current_index"] == 0


def test_update_state_metadata_only_still_fails_without_search(settings):
    brief = _skill_flow_brief(platform="douyin")
    state: dict = {"execution_plan": build_supervisor_execution_plan(brief, {}), "job_id": "sim-job"}
    svc = TaskSupervisorService(settings, "default", "douyin", "default")

    svc._update_state(
        state,
        "crawl_keyword",
        {
            "status": "completed",
            "result": {"comments_collected": 9, "comments_by_video": []},
        },
        brief,
        dry_run=False,
    )

    assert state.get("crawl_done") is not True
    assert state.get("crawl_failures") == 1


@pytest.mark.parametrize("platform", ["douyin", "xiaohongshu"])
def test_simulate_search_zero_comments_then_continue_crawl(settings, platform):
    actions, state = _simulate_crawl_rounds(
        settings,
        _skill_flow_brief(platform=platform),
        [
            _search_phase_partial(platform=platform),
            _crawl_with_comments(platform=platform),
        ],
    )

    assert actions == ["crawl_keyword", "crawl_keyword"]
    assert state.get("crawl_done") is True
    assert state.get("comments_captured", 0) >= 1
    assert state.get("crawl_failures", 0) == 0


@pytest.mark.parametrize("platform", ["douyin", "xiaohongshu"])
def test_simulate_after_search_partial_next_step_is_crawl_not_suspend(settings, platform):
    brief = _skill_flow_brief(platform=platform)
    actions, state = _simulate_crawl_rounds(
        settings,
        brief,
        [_search_phase_partial(platform=platform)],
    )

    assert actions == ["crawl_keyword"]
    decision = plan_driven_supervisor_decision(
        state["execution_plan"],
        brief,
        state,
        stats=mock_interaction_stats(brief),
    )
    assert decision is not None
    assert decision["action"] == "crawl_keyword"
    assert decision["action"] != "suspend"


def test_simulate_three_search_only_rounds_before_comments(settings):
    brief = _skill_flow_brief(platform="douyin")
    partial = _search_phase_partial(platform="douyin")
    actions, state = _simulate_crawl_rounds(
        settings,
        brief,
        [partial, partial, _crawl_with_comments(platform="douyin")],
    )

    assert actions == ["crawl_keyword", "crawl_keyword", "crawl_keyword"]
    assert state.get("crawl_done") is True
    assert int(state.get("crawl_rounds_without_eval") or 0) >= 3


def test_simulate_search_partial_dry_run_matches_live_validation(settings):
    partial = _search_phase_partial(platform="douyin")
    _, dry_state = _simulate_crawl_rounds(
        settings,
        _skill_flow_brief(platform="douyin"),
        [partial],
        dry_run=True,
    )
    _, live_state = _simulate_crawl_rounds(
        settings,
        _skill_flow_brief(platform="douyin"),
        [partial],
        dry_run=False,
    )

    for key in ("crawl_done", "crawl_failures", "last_crawl_error"):
        assert dry_state.get(key) == live_state.get(key)
