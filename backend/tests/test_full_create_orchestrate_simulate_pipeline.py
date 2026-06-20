"""创建任务 → 编排 → 模拟执行 全链路兼容性测试（dry-run，无浏览器/LLM）。

覆盖：
- 各表单 intent 变体（自动/手动单视频/博主主页）
- 主页 URL 误选 single_video 的 intent 纠正
- 抓取参数与表单字段一致（含 comment_days / video_publish_days）
- CommentCrawlerService 接口与 skill_executor 传参兼容
- 主页 0 评论场景不死循环
- 抓取失败后手动继续可回到 crawl_profile
"""
from __future__ import annotations

import copy
import inspect
import uuid
from typing import Any

import pytest

from app.core.config import Settings
from app.schemas.external_task import ExternalTaskCreateRequest
from app.services.comment_crawler_service import CommentCrawlerService
from app.services.external_task_service import normalize_external_create
from app.services.manual_acquisition_service import reconcile_manual_acquisition_mode
from app.services.task_execution_plan import (
    build_supervisor_execution_plan,
    plan_driven_supervisor_decision,
    reset_supervisor_state_for_manual_retry,
)
from tests.task_execution_simulator import (
    build_brief_from_external_payload,
    simulate_planned_execution,
)
from tests.test_external_task_agent_e2e import (
    _build_constraints,
    build_account_home_payload_like_frontend,
)
from tests.test_frontend_payload_alignment import (
    build_auto_task_payload_like_frontend,
    build_manual_task_payload_like_frontend,
)
from tests.test_task_form_orchestration_audit import (
    FORM_VARIANTS,
    audit_execution_plan,
)

PROFILE_URL = (
    "https://www.douyin.com/user/MS4wLjABAAAAR-hiJNkDpOJIXZ7D-H-F7MhLvQo-5q_gGXHP45xq4WXgejcno6YtUnkzlncgy1n5"
)

CRAWL_BY_INTENT = {
    "keyword_auto": "crawl_keyword",
    "single_video": "crawl_content_url",
    "account_home": "crawl_profile",
}


def _settings(tmp_path) -> Settings:
    return Settings(
        storage_root=tmp_path / "storage",
        deepseek_api_key="test-key",
        tenant_auth_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'sim.db'}",
    )


def _unique_payload(payload: dict) -> dict:
    out = copy.deepcopy(payload)
    token = f"pipe-{uuid.uuid4().hex[:8]}"
    correlation = dict(out.get("correlation") or {})
    correlation["external_system"] = correlation.get("external_system") or "huoke_local"
    correlation["external_task_id"] = token
    correlation["idempotency_key"] = token
    out["correlation"] = correlation
    out["auto_execute"] = False
    return out


def _profile_misintent_payload() -> dict:
    token = f"mis-{uuid.uuid4().hex[:8]}"
    return {
        "intent": "single_video",
        "name": "博主主页获客",
        "platform": "douyin",
        "scope": {
            "input_url": PROFILE_URL,
            "comment_days": 3,
            "publish_time_range": "7d",
            "crawl_video_limit": 10,
        },
        "crawl": {"headless": False},
        "evaluation": {
            "target_customer": "意向客户",
            "accept_description": "咨询、询价",
            "reject_signals": ["广告"],
        },
        "outreach": {
            "constraints": _build_constraints(),
            "reply_templates": ["你好"],
            "dm_templates": ["您好"],
        },
        "correlation": {
            "external_system": "huoke_local",
            "external_task_id": token,
            "idempotency_key": token,
        },
        "auto_execute": True,
        "agent_strategy": "douyin_supervisor",
    }


@pytest.fixture
def sim_settings(tmp_path):
    return _settings(tmp_path)


def test_comment_crawler_accepts_comment_days_kwarg():
    """skill_executor 传入的 comment_days 须被 CommentCrawlerService 接受。"""
    sig = inspect.signature(CommentCrawlerService.crawl_profile_comments)
    assert "comment_days" in sig.parameters


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", FORM_VARIANTS)
async def test_create_to_simulate_pipeline_all_form_variants(
    sim_settings,
    variant_name,
    builder,
    expect,
):
    """每种表单变体：校验 → brief → 计划审计 → 模拟执行至配额步。"""
    payload = _unique_payload(builder())
    ExternalTaskCreateRequest.model_validate(payload)

    intent = expect["intent"]
    first_crawl = expect["first_crawl"]

    brief, config = await build_brief_from_external_payload(payload, settings=sim_settings)
    assert config.get("intent") == intent or config.get("acquisition_mode") == intent

    plan = build_supervisor_execution_plan(brief, {})
    issues = audit_execution_plan(plan, expected_first_crawl=first_crawl)
    assert issues == [], f"{variant_name}: {issues}"

    crawl_action = CRAWL_BY_INTENT[intent]
    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        plan=plan,
        simulate_until={crawl_action, "evaluate_leads", "query_stats"},
        run_to_completion=False,
    )

    assert crawl_action in result.actions
    assert "evaluate_leads" in result.actions
    assert "query_stats" in result.actions

    crawl_step = next(row for row in result.trace if row.action == crawl_action)
    params = crawl_step.params
    scope = payload.get("scope") or {}

    if scope.get("comment_days") is not None:
        assert params.get("comment_days") == int(scope["comment_days"])
    if scope.get("publish_time_range") and scope["publish_time_range"] != "unlimited":
        days_map = {"1d": 1, "3d": 3, "7d": 7, "30d": 30}
        expected_publish = days_map.get(scope["publish_time_range"])
        if expected_publish is not None:
            assert params.get("video_publish_days") == expected_publish
    if scope.get("crawl_video_limit") is not None and crawl_action == "crawl_profile":
        limit = int(scope["crawl_video_limit"])
        assert params.get("crawl_video_limit") == limit
        assert params.get("video_limit") == limit


@pytest.mark.asyncio
async def test_profile_url_misintent_corrected_through_pipeline(sim_settings):
    """主页链误选 single_video：归一化 → crawl_profile → 参数完整。"""
    payload = _profile_misintent_payload()
    request = ExternalTaskCreateRequest.model_validate(payload)
    _msg, config, _corr = normalize_external_create(request)

    assert config["intent"] == "account_home"
    assert config["acquisition_mode"] == "account_home"
    assert reconcile_manual_acquisition_mode("single_video", PROFILE_URL, "douyin") == "account_home"

    brief, _ = await build_brief_from_external_payload(payload, settings=sim_settings)
    plan = build_supervisor_execution_plan(brief, {})
    assert plan["steps"][0]["action"] == "crawl_profile"

    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        plan=plan,
        simulate_until={"crawl_profile"},
        run_to_completion=False,
    )
    params = next(row.params for row in result.trace if row.action == "crawl_profile")
    assert params.get("profile_url", "").startswith("https://www.douyin.com/user/")
    assert params.get("comment_days") == 3
    assert params.get("video_publish_days") == 7
    assert params.get("crawl_video_limit") == 10


@pytest.mark.asyncio
async def test_account_home_zero_comments_no_infinite_recrawl(sim_settings):
    """主页 0 评论：模拟执行不应反复 crawl_profile（≤2 次后挂起或完成）。"""
    payload = _unique_payload(build_account_home_payload_like_frontend())
    brief, _ = await build_brief_from_external_payload(payload, settings=sim_settings)
    plan = build_supervisor_execution_plan(brief, {})

    state: dict[str, Any] = {
        "execution_plan": copy.deepcopy(plan),
        "job_id": "sim-zero",
        "_sim_profile_zero_comments": True,
    }
    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        plan=state["execution_plan"],
        run_to_completion=True,
        max_cycles=25,
    )

    crawl_count = result.actions.count("crawl_profile")
    assert crawl_count <= 2, result.actions
    assert result.terminal in {"suspend", "complete", "max_cycles"}
    assert result.state.get("crawl_done") is True
    assert result.state.get("crawl_search_exhausted") is True


@pytest.mark.asyncio
async def test_manual_resume_after_crawl_profile_failed(sim_settings):
    """抓取失败挂起后手动继续：计划回到 crawl_profile 且可决策。"""
    payload = _unique_payload(build_account_home_payload_like_frontend())
    brief, _ = await build_brief_from_external_payload(payload, settings=sim_settings)
    plan = build_supervisor_execution_plan(brief, {})
    plan["steps"][0]["status"] = "failed"
    state = {
        "suspended": True,
        "wake_reason": "抓取失败",
        "execution_plan": plan,
        "crawl_failures": 0,
    }

    reset_supervisor_state_for_manual_retry(state, plan, brief=brief)
    assert not state.get("suspended")
    assert plan["steps"][0]["status"] == "pending"

    decision = plan_driven_supervisor_decision(plan, brief, state)
    assert decision is not None
    assert decision.get("action") == "crawl_profile"
    assert decision.get("params", {}).get("comment_days") is not None


@pytest.mark.asyncio
async def test_full_simulate_run_to_outreach_for_account_home(sim_settings):
    """博主主页：完整模拟至触达步（有评论 mock）。"""
    payload = _unique_payload(build_account_home_payload_like_frontend())
    brief, _ = await build_brief_from_external_payload(payload, settings=sim_settings)
    result = simulate_planned_execution(
        settings=sim_settings,
        brief=brief,
        simulate_until={"reply"},
        run_to_completion=False,
    )
    assert result.actions[0] == "crawl_profile"
    assert "evaluate_leads" in result.actions
    assert "query_stats" in result.actions
    assert "reply" in result.actions
