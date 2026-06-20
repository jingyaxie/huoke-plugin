"""小红书：任务创建 → 编排审计 → 模拟执行（dry-run，无浏览器/LLM）。"""
from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest

from app.core.config import Settings
from app.schemas.external_task import ExternalTaskCreateRequest
from app.services.agent_strategy.registry import SKILL_FLOW_XHS
from app.services.external_task_service import normalize_external_create
from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import build_supervisor_execution_plan
from app.services.task_round_service import round_loop_enabled
from app.services.task_skill_playbook import build_allowed_skills, skill_id_for_supervisor_action
from tests.helpers import API_HEADERS
from tests.task_execution_simulator import (
    build_brief_from_external_payload,
    simulate_planned_execution,
)
from tests.test_external_task_agent_e2e import (
    XHS_NOTE_URL,
    XHS_PROFILE_URL,
    build_xhs_account_home_payload,
    build_xhs_auto_payload,
    build_xhs_manual_payload,
)
from tests.test_task_form_orchestration_audit import (
    _preflight_tactical_steps,
    _step_actions,
    _tactical_from_macro,
    audit_execution_plan,
)
from tests.test_task_planned_execution_simulation import (
    _assert_pipeline_prefix,
    _crawl_action,
)

XHS_VARIANTS: list[tuple[str, callable, dict]] = [
    (
        "keyword_auto",
        build_xhs_auto_payload,
        {"intent": "keyword_auto", "first_crawl": "crawl_keyword"},
    ),
    (
        "single_video",
        build_xhs_manual_payload,
        {"intent": "single_video", "first_crawl": "crawl_content_url"},
    ),
    (
        "account_home",
        build_xhs_account_home_payload,
        {"intent": "account_home", "first_crawl": "crawl_profile"},
    ),
]


def _settings(tmp_path) -> Settings:
    return Settings(
        storage_root=tmp_path / "storage",
        deepseek_api_key="test-key",
        tenant_auth_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'xhs_sim.db'}",
    )


def _unique_payload(builder, tag: str) -> dict:
    payload = copy.deepcopy(builder())
    token = f"xhs-{tag}-{uuid.uuid4().hex[:8]}"
    correlation = dict(payload.get("correlation") or {})
    correlation["external_task_id"] = token
    correlation["idempotency_key"] = token
    payload["correlation"] = correlation
    payload["auto_execute"] = False
    return payload


@pytest.fixture
def xhs_sim_settings(tmp_path):
    return _settings(tmp_path)


@pytest.mark.parametrize("variant_name,builder,expect", XHS_VARIANTS)
def test_xhs_payload_validate_and_normalize(variant_name, builder, expect):
    """三种小红书任务 payload 均可校验并归一化。"""
    raw = builder()
    request = ExternalTaskCreateRequest.model_validate(raw)
    _message, config, _correlation = normalize_external_create(request)

    assert request.platform == "xiaohongshu"
    assert request.agent_strategy == "skill-flow-xiaohongshu"
    assert config["intent"] == expect["intent"]
    assert config["acquisition_mode"] == expect["intent"]
    assert config["platform"] == "xiaohongshu"

    if expect["intent"] == "keyword_auto":
        assert config.get("keyword") == raw["scope"]["keyword"]
    elif expect["intent"] == "single_video":
        assert config.get("video_url") == XHS_NOTE_URL
    else:
        assert config.get("profile_url") == XHS_PROFILE_URL


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", XHS_VARIANTS)
async def test_xhs_create_orchestrate_simulate_local(
    xhs_sim_settings,
    variant_name,
    builder,
    expect,
):
    """本地链路：校验 → brief → 计划审计 → 模拟执行至配额步。"""
    payload = _unique_payload(builder, variant_name)
    intent = expect["intent"]
    first_crawl = expect["first_crawl"]

    brief, config = await build_brief_from_external_payload(payload, settings=xhs_sim_settings)
    assert brief.platform == "xiaohongshu"
    assert config.get("intent") == intent or config.get("acquisition_mode") == intent

    plan = build_supervisor_execution_plan(brief, {})
    issues = audit_execution_plan(plan, expected_first_crawl=first_crawl)
    assert issues == [], f"{variant_name}: {issues}"

    result = simulate_planned_execution(
        settings=xhs_sim_settings,
        brief=brief,
        plan=plan,
        simulate_until={first_crawl, "evaluate_leads", "query_stats"},
        run_to_completion=False,
    )

    assert first_crawl in result.actions
    assert "evaluate_leads" in result.actions
    assert "query_stats" in result.actions

    crawl_step = next(row for row in result.trace if row.action == first_crawl)
    params = crawl_step.params
    scope = payload.get("scope") or {}

    if intent == "keyword_auto":
        assert params.get("keyword") == scope.get("keyword")
    elif intent == "single_video":
        assert params.get("video_url") == XHS_NOTE_URL
    else:
        assert params.get("profile_url") == XHS_PROFILE_URL
        if scope.get("crawl_video_limit") is not None:
            assert params.get("crawl_video_limit") == int(scope["crawl_video_limit"])


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", XHS_VARIANTS)
async def test_xhs_http_preflight_create_orchestrate_simulate(
    flow_client,
    variant_name,
    builder,
    expect,
):
    """HTTP 链路：预检 → 创建 pending → 编排一致性 → 模拟执行至 goal。"""
    client, settings, svc = flow_client
    payload = _unique_payload(builder, variant_name)
    intent = expect["intent"]
    first_crawl = expect["first_crawl"]

    preflight = client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert preflight.status_code == 200, preflight.text
    pf_body = preflight.json()
    assert pf_body["ready"] is True, pf_body
    assert pf_body["blocking_count"] == 0

    pf_actions = _step_actions(_preflight_tactical_steps(pf_body))
    assert first_crawl in pf_actions
    assert "evaluate_leads" in pf_actions

    create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert create.status_code == 200, create.text
    job_body = create.json()
    assert job_body["status"] == "pending"
    assert job_body["auto_execute"] is False

    result_payload = job_body.get("result") or {}
    assert result_payload.get("execution_mode") == "supervisor"
    orch = result_payload.get("orchestration") or {}
    assert orch.get("source") == "supervisor"
    assert orch.get("execution_mode") == "skill_flow"

    brief = TaskBrief.model_validate(orch["task_brief"])
    assert brief.platform == "xiaohongshu"

    exec_plan = build_supervisor_execution_plan(brief, {})
    issues = audit_execution_plan(exec_plan, expected_first_crawl=first_crawl)
    assert not issues, f"[{variant_name}] 执行计划审计失败: {issues}"

    macro_tactical = _tactical_from_macro(orch)
    rebuilt_actions = _step_actions(exec_plan.get("steps") or [])
    assert _step_actions(macro_tactical) == rebuilt_actions
    assert _step_actions(_preflight_tactical_steps(pf_body)) == rebuilt_actions

    loaded = svc.get_job("default", job_body["job_id"])
    assert loaded is not None
    assert loaded.status == "pending"

    brief = brief.model_copy(deep=True)
    if round_loop_enabled(brief):
        brief.goals["round_target_count"] = 2
        brief.constraints["round_target_count"] = 2
    else:
        brief.goals["target_leads"] = 2

    sim = simulate_planned_execution(settings=settings, brief=brief)
    crawl_action = _crawl_action(intent)

    assert sim.actions[0] == crawl_action
    assert sim.terminal == "complete"
    assert sim.completion_outcome == "goal_reached"
    _assert_pipeline_prefix(sim.actions, crawl_action)


def test_xhs_skill_bindings():
    """Supervisor 动作须映射到小红书专用 Skill。"""
    assert skill_id_for_supervisor_action("crawl_keyword", "xiaohongshu") == "xhs-keyword-comments"
    assert skill_id_for_supervisor_action("crawl_profile", "xiaohongshu") == "xhs-profile-comments"
    assert skill_id_for_supervisor_action("crawl_content_url", "xiaohongshu") == "content-comments"
    assert skill_id_for_supervisor_action("reply", "xiaohongshu") == "reply-comment"
    assert skill_id_for_supervisor_action("follow", "xiaohongshu") == "follow-user"

    skills = build_allowed_skills("xiaohongshu", strategy=SKILL_FLOW_XHS)
    crawl_kw = next(row for row in skills if row["supervisor_action"] == "crawl_keyword")
    crawl_profile = next(row for row in skills if row["supervisor_action"] == "crawl_profile")
    assert crawl_kw["skill_id"] == "xhs-keyword-comments"
    assert crawl_profile["skill_id"] == "xhs-profile-comments"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", XHS_VARIANTS)
async def test_xhs_simulate_run_to_outreach(
    xhs_sim_settings,
    variant_name,
    builder,
    expect,
):
    """模拟执行须推进至 reply 触达步（dry-run）。"""
    payload = _unique_payload(builder, variant_name)
    brief, _ = await build_brief_from_external_payload(payload, settings=xhs_sim_settings)
    result = simulate_planned_execution(
        settings=xhs_sim_settings,
        brief=brief,
        simulate_until={"reply"},
        run_to_completion=False,
    )

    first_crawl = expect["first_crawl"]
    assert result.actions[0] == first_crawl
    assert "evaluate_leads" in result.actions
    assert "query_stats" in result.actions
    assert "reply" in result.actions


@pytest.mark.asyncio
async def test_xhs_account_home_zero_comments_no_infinite_recrawl(xhs_sim_settings):
    """主页 0 评论：不应反复 crawl_profile。"""
    payload = _unique_payload(build_xhs_account_home_payload, "zero")
    brief, _ = await build_brief_from_external_payload(payload, settings=xhs_sim_settings)
    plan = build_supervisor_execution_plan(brief, {})

    state: dict[str, Any] = {
        "execution_plan": copy.deepcopy(plan),
        "job_id": "sim-xhs-zero",
        "_sim_profile_zero_comments": True,
    }
    result = simulate_planned_execution(
        settings=xhs_sim_settings,
        brief=brief,
        plan=state["execution_plan"],
        run_to_completion=True,
        max_cycles=25,
        initial_state=state,
    )

    crawl_count = result.actions.count("crawl_profile")
    assert crawl_count <= 2, result.actions
    assert result.terminal in {"suspend", "complete", "max_cycles"}
    assert result.state.get("crawl_done") is True
    assert result.state.get("crawl_search_exhausted") is True
