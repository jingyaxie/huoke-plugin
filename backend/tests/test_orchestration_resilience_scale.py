"""大规模编排韧性测试：提交 → 编排 → 模拟执行（dry-run，无真实抖音抓取）。

- 覆盖全部表单变体 × 多种故障注入场景
- 单步失败不应导致整条流水线异常终止（可恢复场景应继续或合理挂起）
- 自动评估编排计划与执行轨迹的合理性
"""
from __future__ import annotations

import copy
import itertools
import uuid
from typing import Any

import pytest

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJobService, _JobKey
from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import build_supervisor_execution_plan
from tests.helpers import API_HEADERS
from tests.orchestration_evaluator import (
    evaluate_execution_trace,
    evaluate_orchestration_plan,
    evaluate_submission_to_execution,
    format_report,
)
from tests.task_execution_simulator import (
    FaultProfile,
    build_brief_from_external_payload,
    simulate_planned_execution,
)
from tests.test_external_task_agent_e2e import build_account_home_payload_like_frontend
from tests.test_frontend_payload_alignment import (
    build_auto_task_payload_like_frontend,
    build_manual_task_payload_like_frontend,
)
from tests.test_task_form_orchestration_audit import FORM_VARIANTS

CRAWL_BY_INTENT = {
    "keyword_auto": "crawl_keyword",
    "single_video": "crawl_content_url",
    "account_home": "crawl_profile",
}

FAULT_SCENARIOS: list[tuple[str, FaultProfile | None, dict[str, Any]]] = [
    ("baseline", None, {"expect_terminal": {"complete", "suspend"}, "require_recovery": False}),
    (
        "crawl_fail_once",
        FaultProfile(fail_first_n={"crawl_keyword": 1, "crawl_content_url": 1, "crawl_profile": 1}),
        {"expect_terminal": {"complete", "suspend"}, "require_recovery": True},
    ),
    (
        "evaluate_fail_once",
        FaultProfile(fail_first_n={"evaluate_leads": 1}),
        {"expect_terminal": {"complete", "suspend"}, "require_recovery": True},
    ),
    (
        "stats_fail_once",
        FaultProfile(fail_first_n={"query_stats": 1}),
        {"expect_terminal": {"complete", "suspend"}, "require_recovery": True},
    ),
    (
        "outreach_reply_fail_once",
        FaultProfile(fail_first_n={"reply": 1}),
        {"expect_terminal": {"complete", "suspend"}, "require_recovery": True},
    ),
    (
        "crawl_login_terminal",
        FaultProfile(
            fail_first_n={"crawl_keyword": 99, "crawl_content_url": 99, "crawl_profile": 99},
            error_message="需要登录 cookie",
            terminal_actions=frozenset({"crawl_keyword", "crawl_content_url", "crawl_profile"}),
        ),
        {"expect_terminal": {"suspend"}, "require_recovery": False},
    ),
    (
        "multi_step_transient",
        FaultProfile(
            fail_first_n={
                "crawl_keyword": 1,
                "crawl_content_url": 1,
                "crawl_profile": 1,
                "evaluate_leads": 1,
                "query_stats": 1,
                "reply": 1,
            }
        ),
        {"expect_terminal": {"complete", "suspend"}, "require_recovery": True},
    ),
]

# 参数化规模：8 变体 × 7 故障 ≈ 56；再加 24 随机组合 ≈ 80
SCALE_VARIANTS = FORM_VARIANTS
SCALE_FAULTS = FAULT_SCENARIOS


def _settings(tmp_path) -> Settings:
    return Settings(
        storage_root=tmp_path / "storage",
        deepseek_api_key="test-key",
        tenant_auth_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'scale.db'}",
    )


def _unique_payload(builder, tag: str) -> dict:
    payload = copy.deepcopy(builder())
    token = f"scale-{tag}-{uuid.uuid4().hex[:8]}"
    correlation = dict(payload.get("correlation") or {})
    correlation["external_task_id"] = token
    correlation["idempotency_key"] = token
    payload["correlation"] = correlation
    payload["auto_execute"] = False
    return payload


def _prepare_brief_for_fast_run(brief: TaskBrief) -> TaskBrief:
    """缩小目标以便在配额内快速跑完完整流水线。"""
    brief = brief.model_copy(deep=True)
    from app.services.task_round_service import round_loop_enabled

    if round_loop_enabled(brief):
        brief.goals["round_target_count"] = 3
        brief.constraints["round_target_count"] = 3
        brief.goals["max_rounds"] = 1
        brief.constraints["max_rounds"] = 1
    else:
        brief.goals["target_leads"] = 3
    return brief


def _crawl_action_for_intent(intent: str) -> str:
    return CRAWL_BY_INTENT[intent]


def _fault_profile_for_intent(profile: FaultProfile | None, crawl_action: str) -> FaultProfile | None:
    if profile is None:
        return None
    generic_keys = {"crawl_keyword", "crawl_content_url", "crawl_profile"}
    fail_first_n: dict[str, int] = {}
    for key, val in profile.fail_first_n.items():
        if key in generic_keys:
            if key == crawl_action:
                fail_first_n[key] = val
        else:
            fail_first_n[key] = val
    terminal_actions = {
        a
        for a in profile.terminal_actions
        if a not in generic_keys or a == crawl_action
    }
    return FaultProfile(
        fail_first_n=fail_first_n,
        error_message=profile.error_message,
        terminal_actions=frozenset(terminal_actions),
    )


@pytest.fixture
def scale_settings(tmp_path):
    return _settings(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", SCALE_VARIANTS)
@pytest.mark.parametrize("fault_name,fault_profile,expect_fault", SCALE_FAULTS)
async def test_scale_variant_with_fault_injection(
    scale_settings,
    variant_name,
    builder,
    expect,
    fault_name,
    fault_profile,
    expect_fault,
):
    """每种表单 × 每种故障：编排审计 + 模拟执行 + 自动评估。"""
    payload = _unique_payload(builder, f"{variant_name}-{fault_name}")
    intent = expect["intent"]
    first_crawl = expect["first_crawl"]
    crawl_action = _crawl_action_for_intent(intent)

    brief, _config = await build_brief_from_external_payload(payload, settings=scale_settings)
    brief = _prepare_brief_for_fast_run(brief)

    plan = build_supervisor_execution_plan(brief, {})
    plan_report = evaluate_orchestration_plan(plan, expected_first_crawl=first_crawl)
    assert plan_report.passed, format_report(plan_report)

    profile = _fault_profile_for_intent(fault_profile, crawl_action)
    result = simulate_planned_execution(
        settings=scale_settings,
        brief=brief,
        plan=plan,
        fault_profile=profile,
        max_cycles=100,
    )

    exec_report = evaluate_execution_trace(
        result,
        brief=brief,
        expected_first_crawl=crawl_action,
        allow_suspend="suspend" in expect_fault["expect_terminal"],
    )
    merged = evaluate_submission_to_execution(plan_report=plan_report, exec_report=exec_report)

    assert result.terminal in expect_fault["expect_terminal"], (
        f"[{variant_name}/{fault_name}] terminal={result.terminal} "
        f"actions={result.actions[-8:]} failures={result.failure_events}"
    )

    if expect_fault.get("require_recovery") and result.failure_events:
        resilient = (
            result.recovered_actions
            or result.progressed_after_failure
            or result.terminal == "suspend"
        )
        assert resilient, (
            f"[{variant_name}/{fault_name}] 有失败但流程未继续: "
            f"failures={result.failure_events} terminal={result.terminal} actions={result.actions}"
        )

    assert merged.passed, f"[{variant_name}/{fault_name}]\n{format_report(merged)}"


@pytest.mark.asyncio
async def test_http_submit_orchestrate_simulate_with_auto_eval(flow_client):
    """HTTP 全链路：预检 → 创建 → 编排审计 → 模拟执行 → 自动评估。"""
    client, settings, _svc = flow_client
    cases = [
        ("auto", build_auto_task_payload_like_frontend, "keyword_auto", "crawl_keyword"),
        ("manual", build_manual_task_payload_like_frontend, "single_video", "crawl_content_url"),
        ("home", build_account_home_payload_like_frontend, "account_home", "crawl_profile"),
    ]

    for tag, builder, intent, first_crawl in cases:
        payload = _unique_payload(builder, tag)

        preflight = client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
        assert preflight.status_code == 200, preflight.text
        pf = preflight.json()
        assert pf["ready"] is True

        create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
        assert create.status_code == 200, create.text
        body = create.json()
        assert body["status"] == "pending"

        orch = (body.get("result") or {}).get("orchestration") or {}
        brief = TaskBrief.model_validate(orch["task_brief"])
        brief = _prepare_brief_for_fast_run(brief)

        plan = build_supervisor_execution_plan(brief, {})
        plan_report = evaluate_orchestration_plan(plan, expected_first_crawl=first_crawl)

        pf_steps = [
            str(s.get("action") or "")
            for s in (pf.get("orchestration") or {}).get("steps") or []
            if isinstance(s, dict)
        ]
        created_steps = [str(s.get("action") or "") for s in plan.get("steps") or []]

        result = simulate_planned_execution(
            settings=settings,
            brief=brief,
            plan=plan,
            fault_profile=FaultProfile(fail_first_n={first_crawl: 1, "evaluate_leads": 1}),
        )
        exec_report = evaluate_execution_trace(
            result,
            brief=brief,
            expected_first_crawl=first_crawl,
        )
        merged = evaluate_submission_to_execution(
            plan_report=plan_report,
            exec_report=exec_report,
            preflight_actions=pf_steps,
            created_actions=created_steps,
        )
        assert merged.passed, f"[http/{tag}]\n{format_report(merged)}"
        assert result.terminal in {"complete", "suspend"}
        assert result.progressed_after_failure or result.terminal == "suspend", (
            f"[http/{tag}] transient 失败后流程应继续或挂起"
        )


@pytest.mark.asyncio
async def test_job_service_dry_run_supervisor_not_mocked(job_service):
    """Job 服务 + 真实 Supervisor dry_run：不 mock 执行层，验证端到端可完成。"""
    from app.schemas.external_task import ExternalTaskCreateRequest
    from app.services.external_task_service import normalize_external_create

    svc, settings = job_service
    payload = build_auto_task_payload_like_frontend()
    _msg, config, _corr = normalize_external_create(ExternalTaskCreateRequest.model_validate(payload))
    config = dict(config)
    config["target_count"] = 3

    job = await svc.submit_async(
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message=payload.get("name") or "scale dry_run",
        auto_execute=False,
        run_mode="dry_run",
        config=config,
        agent_strategy=payload.get("agent_strategy"),
    )
    assert job.result.get("execution_mode") == "supervisor"

    await svc._run_job(_JobKey(tenant_id=job.tenant_id, job_id=job.job_id), settings)
    loaded = svc.get_job(job.tenant_id, job.job_id)
    assert loaded is not None
    assert loaded.status in {"completed", "pending"}, (
        f"dry_run 不应 failed/dead_letter: status={loaded.status} summary={loaded.result.get('summary')}"
    )
    cycles = loaded.result.get("supervisor_cycles") or []
    assert cycles, "应有 supervisor 执行记录"
    actions = [c.get("action") for c in cycles if c.get("action")]
    assert "crawl_keyword" in actions or loaded.status == "pending"


@pytest.mark.asyncio
async def test_parallel_jobs_different_accounts_complete(job_service, monkeypatch):
    """多账号并行提交：单账号 mutex 不应拖垮其他账号任务。"""
    svc, settings = job_service

    async def fast_dry_run(self, **kwargs):
        return {
            **kwargs.get("job_result", {}),
            "status": "completed",
            "summary": "parallel ok",
            "dry_run": True,
            "supervisor_cycles": [{"cycle": 1, "action": "crawl_keyword", "ok": True}],
        }

    monkeypatch.setattr(
        "app.services.agent_async_job_service.TaskSupervisorService.run",
        fast_dry_run,
    )

    jobs = []
    for acct in ("acct-a", "acct-b", "acct-c"):
        job = await svc.submit_async(
            tenant_id="default",
            platform="douyin",
            account_id=acct,
            message="并行测试",
            auto_execute=False,
            run_mode="dry_run",
        )
        jobs.append(job)

    for job in jobs:
        await svc._run_job(_JobKey(tenant_id=job.tenant_id, job_id=job.job_id), settings)

    for job in jobs:
        loaded = svc.get_job(job.tenant_id, job.job_id)
        assert loaded.status == "completed"


def _random_scope_permutations() -> list[dict[str, Any]]:
    keywords = ["团餐配送", "健身房", "装修", "奶茶加盟"]
    regions = ["深圳", "广州", None]
    comment_days = [1, 3, 7]
    publish = ["1d", "3d", "7d", "unlimited"]
    targets = [3, 5, 10]
    combos = itertools.product(keywords, regions, comment_days, publish, targets)
    out = []
    for kw, region, cd, pt, tgt in itertools.islice(combos, 24):
        scope: dict[str, Any] = {
            "keyword": kw,
            "target_count": tgt,
            "comment_days": cd,
            "publish_time_range": pt,
        }
        if region:
            scope["region"] = region
        out.append(scope)
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_idx", range(24))
async def test_mass_random_auto_task_permutations(scale_settings, scope_idx):
    """24 组随机 scope 组合：提交归一化 → 计划 → 模拟 → 评估。"""
    scopes = _random_scope_permutations()
    scope = scopes[scope_idx]
    payload = build_auto_task_payload_like_frontend()
    payload["scope"].update(scope)
    payload = _unique_payload(lambda: payload, f"rand-{scope_idx}")

    brief, _ = await build_brief_from_external_payload(payload, settings=scale_settings)
    brief = _prepare_brief_for_fast_run(brief)
    plan = build_supervisor_execution_plan(brief, {})

    plan_report = evaluate_orchestration_plan(plan, expected_first_crawl="crawl_keyword")
    result = simulate_planned_execution(
        settings=scale_settings,
        brief=brief,
        plan=plan,
        fault_profile=FaultProfile(fail_first_n={"crawl_keyword": 1}) if scope_idx % 3 == 0 else None,
    )
    exec_report = evaluate_execution_trace(result, brief=brief, expected_first_crawl="crawl_keyword")
    merged = evaluate_submission_to_execution(plan_report=plan_report, exec_report=exec_report)

    assert merged.passed, f"[rand-{scope_idx} scope={scope}]\n{format_report(merged)}"
    assert result.terminal in {"complete", "suspend"}


@pytest.fixture
def job_service(tmp_path, monkeypatch):
    AgentAsyncJobService._instance = None
    settings = Settings(storage_root=tmp_path / "storage")
    svc = AgentAsyncJobService.get(settings)
    monkeypatch.setattr(svc, "_ensure_workers", lambda: None)

    async def mock_brief(message, **kwargs):
        return TaskBrief(
            title="规模测试",
            brief_md="# 规模测试",
            platform="douyin",
            keyword="团餐配送",
            region="深圳",
            goals={"target_leads": 3, "comment_days": 3},
            reasoning="mock",
            confidence=0.9,
            llm_available=True,
            llm_fallback=False,
        )

    monkeypatch.setattr(
        "app.services.agent_job_plan_service.generate_task_brief",
        mock_brief,
    )
    yield svc, settings
    for worker in svc._workers:
        worker.cancel()
    AgentAsyncJobService._instance = None
