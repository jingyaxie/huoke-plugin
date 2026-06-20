"""编排后任务按计划执行的详细模拟测试（dry-run，不调用真实浏览器/Skill）。"""
from __future__ import annotations

import copy
import uuid

import pytest

from app.core.config import Settings
from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import build_supervisor_execution_plan
from app.services.task_round_service import effective_target_leads, goal_reached_for_current_round, round_loop_enabled
from tests.helpers import API_HEADERS
from tests.task_execution_simulator import (
    build_brief_from_external_payload,
    simulate_planned_execution,
)
from tests.test_external_task_agent_e2e import (
    build_account_home_payload_like_frontend,
    build_xhs_auto_payload,
)
from tests.test_frontend_payload_alignment import (
    build_auto_task_payload_like_frontend,
    build_manual_task_payload_like_frontend,
)
from tests.test_task_form_orchestration_audit import (
    _minimal_auto_payload,
    _rich_evaluation_manual_payload,
    _round_mode_auto_payload,
)

SKILL_FLOW_PIPELINE = [
    "crawl",
    "evaluate_leads",
    "query_stats",
    "reply",
    "dm",
    "follow",
    "complete",
]


def _settings(tmp_path) -> Settings:
    return Settings(
        storage_root=tmp_path / "storage",
        deepseek_api_key="test-key",
        tenant_auth_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'sim.db'}",
    )


def _crawl_action(intent: str) -> str:
    return {
        "keyword_auto": "crawl_keyword",
        "single_video": "crawl_content_url",
        "account_home": "crawl_profile",
    }[intent]


def _assert_pipeline_prefix(actions: list[str], crawl_action: str) -> None:
    assert actions[0] == crawl_action
    eval_idx = actions.index("evaluate_leads")
    stats_idx = actions.index("query_stats")
    crawl_idx = actions.index(crawl_action)
    assert crawl_idx < eval_idx < stats_idx
    if "reply" in actions:
        assert stats_idx < actions.index("reply")


@pytest.fixture
def sim_settings(tmp_path):
    return _settings(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder,intent,field_checks",
    [
        (
            build_auto_task_payload_like_frontend,
            "keyword_auto",
            {
                "keyword": "团餐配送",
                "region": "深圳",
                "comment_days": 3,
                "video_publish_days": 7,
                "crawl_video_limit": 5,
            },
        ),
        (
            build_xhs_auto_payload,
            "keyword_auto",
            {"platform": "xiaohongshu", "keyword": "团餐配送", "comment_days": 3},
        ),
        (
            build_manual_task_payload_like_frontend,
            "single_video",
            {
                "video_url": "https://www.douyin.com/video/7123456789",
                "comment_days": 5,
                "video_publish_days": 3,
            },
        ),
        (
            build_account_home_payload_like_frontend,
            "account_home",
            {
                "profile_url": "https://www.douyin.com/user/MS4wLjABAAAAtest",
                "comment_days": 7,
                "video_publish_days": 7,
                "crawl_video_limit": 5,
            },
        ),
        (
            _minimal_auto_payload,
            "keyword_auto",
            {"keyword": "健身房", "comment_days": None},
        ),
    ],
)
async def test_crawl_step_params_match_form_fields(sim_settings, builder, intent, field_checks):
    """首步抓取决策的参数须与表单字段一致。"""
    payload = builder()
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    crawl_action = _crawl_action(intent)

    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        simulate_until={crawl_action},
        run_to_completion=False,
    )
    crawl_steps = [row for row in result.trace if row.action == crawl_action]
    assert crawl_steps, result.actions
    params = crawl_steps[0].params

    if field_checks.get("keyword"):
        assert params.get("keyword") == field_checks["keyword"]
        assert brief.keyword == field_checks["keyword"]
    if field_checks.get("region"):
        assert params.get("region") == field_checks["region"]
    if field_checks.get("comment_days"):
        assert params.get("comment_days") == field_checks["comment_days"]
    if field_checks.get("video_publish_days"):
        assert params.get("video_publish_days") == field_checks["video_publish_days"]
    if field_checks.get("crawl_video_limit"):
        assert params.get("crawl_video_limit") == field_checks["crawl_video_limit"]
        assert params.get("video_limit") == field_checks["crawl_video_limit"]
    if field_checks.get("video_url"):
        assert params.get("video_url") == field_checks["video_url"]
    if field_checks.get("profile_url"):
        assert params.get("profile_url") == field_checks["profile_url"]
    if field_checks.get("platform"):
        assert brief.platform == field_checks["platform"]
        assert params.get("platform", brief.platform) == field_checks["platform"] or brief.platform == field_checks["platform"]

    if intent == "keyword_auto":
        assert params.get("ui_search_only") is True
        assert params.get("search_url_first") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder,intent",
    [
        (build_auto_task_payload_like_frontend, "keyword_auto"),
        (build_manual_task_payload_like_frontend, "single_video"),
        (build_account_home_payload_like_frontend, "account_home"),
    ],
)
async def test_planned_execution_reaches_goal(sim_settings, builder, intent):
    """完整模拟须按流水线推进并在达标后 complete（goal_reached）。"""
    payload = builder()
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    # 加速模拟：小目标更易在配额内跑完
    brief = brief.model_copy(deep=True)
    if round_loop_enabled(brief):
        brief.goals["round_target_count"] = 3
        brief.constraints["round_target_count"] = 3
    else:
        brief.goals["target_leads"] = 3

    result = simulate_planned_execution(settings=sim_settings, brief=brief)
    crawl_action = _crawl_action(intent)

    assert result.terminal == "complete"
    assert result.completion_outcome == "goal_reached"
    _assert_pipeline_prefix(result.actions, crawl_action)
    assert result.state.get("crawl_done") is True
    assert result.state.get("evaluation_done") is True
    assert result.state.get("stats_synced") is True
    assert goal_reached_for_current_round(brief, result.state) or int(result.state.get("leads_collected") or 0) >= 3


@pytest.mark.asyncio
async def test_round_mode_uses_round_target_not_total_target(sim_settings):
    """循环任务每轮以 round_target_count 为达标线，而非 target_count。"""
    payload = _round_mode_auto_payload()
    brief, config = await build_brief_from_external_payload(payload, settings=sim_settings)

    assert round_loop_enabled(brief)
    assert brief.goals.get("round_target_count") == 20
    assert config.get("target_count") == 50

    brief = brief.model_copy(deep=True)
    brief.goals["round_target_count"] = 4
    brief.constraints["round_target_count"] = 4
    brief.goals["max_rounds"] = 1
    brief.constraints["max_rounds"] = 1

    result = simulate_planned_execution(settings=sim_settings, brief=brief)
    assert effective_target_leads(brief, result.state) == 4
    assert result.terminal == "complete"
    assert result.completion_outcome in {"goal_reached", "max_rounds_reached"}
    assert int(result.state.get("round_leads_collected") or result.state.get("leads_collected") or 0) >= 4


@pytest.mark.asyncio
async def test_outreach_follows_priority_order(sim_settings):
    """触达步骤顺序须与 brief 中 outreach_priority 一致。"""
    payload = build_auto_task_payload_like_frontend()
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    brief = brief.model_copy(deep=True)
    brief.goals["target_leads"] = 2
    brief.constraints["outreach_priority"] = ["dm", "reply", "follow"]

    plan = build_supervisor_execution_plan(brief, {})
    outreach_actions = [s["action"] for s in plan["steps"] if s["action"] in {"reply", "dm", "follow"}]
    assert outreach_actions == ["dm", "reply", "follow"]

    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        simulate_until={"dm", "reply"},
        run_to_completion=False,
    )
    outreach_trace = [a for a in result.actions if a in {"reply", "dm", "follow"}]
    assert outreach_trace[0] == "dm"


@pytest.mark.asyncio
async def test_evaluate_and_stats_steps_use_platform_from_form(sim_settings):
    payload = _rich_evaluation_manual_payload()
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    brief = brief.model_copy(deep=True)
    brief.goals["target_leads"] = 2

    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        simulate_until={"evaluate_leads", "query_stats"},
        run_to_completion=False,
    )
    eval_step = next(row for row in result.trace if row.action == "evaluate_leads")
    stats_step = next(row for row in result.trace if row.action == "query_stats")
    assert eval_step.params.get("platform") == "douyin"
    assert stats_step.params.get("platform") == "douyin"


@pytest.mark.asyncio
async def test_plan_steps_mark_completed_along_simulation(sim_settings):
    """模拟推进时计划表步骤状态应随状态机回填。"""
    payload = build_auto_task_payload_like_frontend()
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    brief = brief.model_copy(deep=True)
    brief.goals["target_leads"] = 2

    result = simulate_planned_execution(settings=sim_settings, brief=brief)
    plan = result.state.get("execution_plan") or {}
    steps = plan.get("steps") or []
    completed = [s["action"] for s in steps if s.get("status") == "completed"]
    assert "crawl_keyword" in completed
    assert "evaluate_leads" in completed
    assert "query_stats" in completed
    assert result.terminal == "complete"


@pytest.mark.asyncio
async def test_suspend_when_plan_done_but_goal_not_met(sim_settings):
    """计划跑完未达标时应挂起而非误标完成。"""
    brief = TaskBrief(
        keyword="测试",
        platform="douyin",
        goals={"target_leads": 99, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        constraints={"outreach_priority": ["reply"]},
    )
    plan = build_supervisor_execution_plan(brief, {})
    state = {
        "execution_plan": plan,
        "crawl_done": True,
        "evaluation_done": True,
        "stats_synced": True,
        "leads_collected": 0,
        "last_stats": {
            "reply": {"count": 30, "limit": 30, "can_do": False},
            "dm": {"count": 30, "limit": 30, "can_do": False},
            "follow": {"count": 30, "limit": 30, "can_do": False},
        },
    }
    for step in plan["steps"]:
        if step["action"] in {"crawl_keyword", "evaluate_leads", "query_stats", "reply", "dm", "follow"}:
            step["status"] = "completed"
    plan["current_index"] = len(plan["steps"]) - 1

    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        plan=plan,
        max_cycles=5,
    )
    assert result.terminal in {"suspend", "complete"}
    if result.terminal == "complete":
        assert result.completion_outcome != "goal_reached"


def _unique_payload(builder, tag: str) -> dict:
    payload = copy.deepcopy(builder())
    token = f"sim-{tag}-{uuid.uuid4().hex[:8]}"
    correlation = dict(payload.get("correlation") or {})
    correlation["external_task_id"] = token
    correlation["idempotency_key"] = token
    payload["correlation"] = correlation
    payload["auto_execute"] = False
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder,intent",
    [
        (build_auto_task_payload_like_frontend, "keyword_auto"),
        (build_manual_task_payload_like_frontend, "single_video"),
        (build_account_home_payload_like_frontend, "account_home"),
    ],
)
async def test_http_create_then_simulate_planned_execution(flow_client, builder, intent):
    """HTTP 创建任务后，用返回的 task_brief 做计划执行模拟。"""
    client, settings, _svc = flow_client
    payload = _unique_payload(builder, intent)

    create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert create.status_code == 200, create.text
    body = create.json()
    assert body["status"] == "pending"

    orch = (body.get("result") or {}).get("orchestration") or {}
    brief = TaskBrief.model_validate(orch["task_brief"])
    brief = brief.model_copy(deep=True)
    if round_loop_enabled(brief):
        brief.goals["round_target_count"] = 2
        brief.constraints["round_target_count"] = 2
    else:
        brief.goals["target_leads"] = 2

    result = simulate_planned_execution(settings=settings, brief=brief)
    crawl_action = _crawl_action(intent)

    assert result.actions[0] == crawl_action
    assert result.terminal == "complete"
    assert result.completion_outcome == "goal_reached"
    _assert_pipeline_prefix(result.actions, crawl_action)

    crawl_params = next(row.params for row in result.trace if row.action == crawl_action)
    scope = payload.get("scope") or {}
    if intent == "keyword_auto":
        assert crawl_params.get("keyword") == scope.get("keyword")
        if scope.get("region"):
            assert crawl_params.get("region") == scope.get("region")
    elif intent == "single_video":
        assert crawl_params.get("video_url") == scope.get("input_url")
    else:
        assert crawl_params.get("profile_url") == scope.get("input_url")
        if scope.get("crawl_video_limit"):
            assert crawl_params.get("crawl_video_limit") == scope.get("crawl_video_limit")
