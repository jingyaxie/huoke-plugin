"""表单提交 → 任务编排 → 模拟执行（standalone-browse-douyin，dry-run，不真抓数据）。

覆盖三种 intent（关键词 / 单视频 / 主页），验证：
- ExternalTaskCreateRequest 校验与 normalize
- brief 构建与 standalone 策略识别
- 编排计划为 standalone_browse 流水线（无 evaluate / 分步触达）
- 表单字段映射到 brief_to_standalone_config
- HTTP 预检 orchestration 预览
- simulate_planned_execution 跑至 complete
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest

from app.core.config import Settings
from app.schemas.external_task import ExternalTaskCreateRequest
from app.services.external_task_service import normalize_external_create
from app.services.standalone_browse_adapter import (
    STANDALONE_PIPELINE,
    brief_to_standalone_config,
    is_standalone_browse_brief,
)
from app.services.task_execution_plan import build_supervisor_execution_plan
from tests.helpers import API_HEADERS
from tests.task_execution_simulator import (
    build_brief_from_external_payload,
    mock_standalone_crawl_result,
    simulate_planned_execution,
)
from tests.test_frontend_payload_alignment import (
    STANDALONE_STRATEGY,
    build_account_home_payload_standalone_like_frontend,
    build_auto_task_payload_standalone_like_frontend,
    build_auto_task_payload_like_frontend,
    build_manual_task_payload_standalone_like_frontend,
)

CRAWL_ACTIONS = frozenset({"crawl_keyword", "crawl_content_url", "crawl_profile"})
OUTREACH_ACTIONS = frozenset({"reply", "dm", "follow"})

STANDALONE_VARIANTS: list[tuple[str, callable, dict[str, Any]]] = [
    (
        "standalone_auto",
        build_auto_task_payload_standalone_like_frontend,
        {"intent": "keyword_auto", "first_crawl": "crawl_keyword"},
    ),
    (
        "standalone_manual",
        build_manual_task_payload_standalone_like_frontend,
        {"intent": "single_video", "first_crawl": "crawl_content_url"},
    ),
    (
        "standalone_account_home",
        build_account_home_payload_standalone_like_frontend,
        {"intent": "account_home", "first_crawl": "crawl_profile"},
    ),
]


def _settings(tmp_path) -> Settings:
    return Settings(
        storage_root=tmp_path / "storage",
        deepseek_api_key="test-key",
        tenant_auth_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'standalone_sim.db'}",
    )


def _unique_payload(builder) -> dict:
    payload = copy.deepcopy(builder())
    token = f"standalone-sim-{uuid.uuid4().hex[:8]}"
    correlation = dict(payload.get("correlation") or {})
    correlation["external_task_id"] = token
    correlation["idempotency_key"] = token
    payload["correlation"] = correlation
    payload["auto_execute"] = False
    return payload


def _step_actions(plan: dict[str, Any]) -> list[str]:
    steps = plan.get("steps") or []
    return [str(row.get("action") or "") for row in steps if isinstance(row, dict)]


def audit_standalone_execution_plan(plan: dict[str, Any], *, expected_first_crawl: str) -> list[str]:
    issues: list[str] = []
    if plan.get("pipeline") != STANDALONE_PIPELINE:
        issues.append(f"pipeline 应为 {STANDALONE_PIPELINE}，实际为 {plan.get('pipeline')}")
    actions = _step_actions(plan)
    if not actions:
        return ["执行计划无步骤"]
    if actions[0] != expected_first_crawl:
        issues.append(f"首步应为 {expected_first_crawl}，实际为 {actions[0]}")
    if "evaluate_leads" in actions:
        issues.append("standalone 计划不应包含 evaluate_leads")
    outreach = [a for a in actions if a in OUTREACH_ACTIONS]
    if outreach:
        issues.append(f"standalone 计划不应包含分步触达: {outreach}")
    for required in ("query_stats", "complete"):
        if required not in actions:
            issues.append(f"缺少步骤: {required}")
    crawl_count = sum(1 for a in actions if a in CRAWL_ACTIONS)
    if crawl_count != 1:
        issues.append(f"应仅 1 个抓取步，实际 {crawl_count}")
    return issues


@pytest.fixture
def sim_settings(tmp_path):
    return _settings(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", STANDALONE_VARIANTS)
async def test_form_to_brief_and_standalone_plan(sim_settings, variant_name, builder, expect):
    payload = _unique_payload(builder)
    ExternalTaskCreateRequest.model_validate(payload)
    _message, config, _correlation = normalize_external_create(
        ExternalTaskCreateRequest.model_validate(payload)
    )

    brief, _cfg = await build_brief_from_external_payload(payload, settings=sim_settings)
    assert is_standalone_browse_brief(brief)
    assert brief.agent_strategy == STANDALONE_STRATEGY

    plan = build_supervisor_execution_plan(brief, {})
    issues = audit_standalone_execution_plan(plan, expected_first_crawl=expect["first_crawl"])
    assert issues == [], f"{variant_name}: {issues}"

    crawl_step = next(s for s in plan["steps"] if s["action"] == expect["first_crawl"])
    params = crawl_step.get("params") or {}
    standalone_cfg = brief_to_standalone_config(brief, params, action=expect["first_crawl"])

    if expect["intent"] == "keyword_auto":
        assert config.get("keyword") == standalone_cfg.keyword
        assert config.get("region") == (standalone_cfg.region or "")
        assert standalone_cfg.target_precise_leads == int(config.get("target_count") or 0)
    elif expect["intent"] == "single_video":
        assert standalone_cfg.video_url == config.get("video_url")
        assert standalone_cfg.acquisition_mode == "single_video"
    else:
        assert standalone_cfg.profile_url == config.get("profile_url")
        assert standalone_cfg.acquisition_mode == "account_home"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", STANDALONE_VARIANTS)
async def test_simulate_standalone_pipeline_to_complete(sim_settings, variant_name, builder, expect):
    payload = _unique_payload(builder)
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    plan = build_supervisor_execution_plan(brief, {})
    assert "query_stats" in _step_actions(plan)

    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        plan=plan,
        run_to_completion=True,
    )

    assert result.terminal == "complete", f"{variant_name}: trace={result.actions}"
    assert "evaluate_leads" not in result.actions
    assert not OUTREACH_ACTIONS.intersection(result.actions)
    assert expect["first_crawl"] in result.actions
    assert result.state.get("crawl_done") is True
    qualified = int(result.state.get("leads_qualified") or 0)
    collected = int(result.state.get("leads_collected") or 0)
    assert qualified > 0 or collected > 0


@pytest.mark.asyncio
async def test_simulate_standalone_runs_query_stats_when_target_not_met(sim_settings):
    """目标未达成时模拟器应继续执行 query_stats（不提前 goal_reached 退出）。"""
    payload = _unique_payload(build_auto_task_payload_standalone_like_frontend)
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    brief.goals["target_leads"] = 999
    plan = build_supervisor_execution_plan(brief, {})

    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        plan=plan,
        run_to_completion=True,
    )

    assert "query_stats" in result.actions
    assert result.terminal in {"complete", "suspend"}
    assert "evaluate_leads" not in result.actions


@pytest.mark.asyncio
async def test_skill_flow_plan_unchanged_regression(sim_settings):
    """默认 skill-flow 策略仍走 evaluate + 触达流水线（与 standalone 隔离）。"""
    payload = _unique_payload(build_auto_task_payload_like_frontend)
    brief, _config = await build_brief_from_external_payload(payload, settings=sim_settings)
    assert not is_standalone_browse_brief(brief)

    plan = build_supervisor_execution_plan(brief, {})
    actions = _step_actions(plan)
    assert "evaluate_leads" in actions
    assert plan.get("pipeline") != STANDALONE_PIPELINE


def test_mock_standalone_crawl_result_shape():
    """模拟抓取结果字段与 Supervisor _update_state standalone 分支兼容。"""
    from app.services.task_brief_service import TaskBrief

    brief = TaskBrief(
        brief_md="test",
        platform="douyin",
        keyword="团餐",
        agent_strategy=STANDALONE_STRATEGY,
    )
    brief.goals["target_leads"] = 5
    result = mock_standalone_crawl_result("crawl_keyword", brief, target=5)
    assert result["standalone_browse"] is True
    assert result["precise_lead_count"] > 0
    assert "inline_outreach" in result


@pytest.mark.parametrize("variant_name,builder,_expect", STANDALONE_VARIANTS)
def test_preflight_http_standalone_orchestration(api_client, variant_name, builder, _expect):
    payload = _unique_payload(builder)
    resp = api_client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready"] is True

    orch = body.get("orchestration") or {}
    steps = orch.get("steps") or []
    actions = [str(row.get("action") or "") for row in steps]
    assert "evaluate_leads" not in actions
    assert not OUTREACH_ACTIONS.intersection(actions)
    assert any(a in CRAWL_ACTIONS for a in actions)
    assert "query_stats" in actions
