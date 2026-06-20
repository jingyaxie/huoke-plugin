"""任务创建表单变体 → 预检接受 → 编排/执行规划合理性审计（不执行任务）。

覆盖三种 intent、多平台与可选字段组合，验证：
- 预检 gate 是否通过
- 创建后宏观编排与战术执行计划是否一致
- 步骤顺序是否符合「抓取→评估→配额→触达→结束」流水线
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest

from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import build_supervisor_execution_plan
from tests.helpers import API_HEADERS
from tests.test_external_task_agent_e2e import (
    build_account_home_payload_like_frontend,
    build_xhs_account_home_payload,
    build_xhs_auto_payload,
    build_xhs_manual_payload,
)
from tests.test_frontend_payload_alignment import (
    DEFAULT_SETTINGS,
    build_auto_task_payload_like_frontend,
    build_manual_task_payload_like_frontend,
)

# --- 表单变体定义（镜像前端各对话框字段组合）---

CRAWL_ACTIONS = frozenset({"crawl_keyword", "crawl_content_url", "crawl_profile"})
OUTREACH_ACTIONS = frozenset({"reply", "dm", "follow"})
PIPELINE_ORDER = ["crawl", "evaluate", "stats", "outreach", "complete"]


def _build_constraints(**extra):
    base = {
        "comment_dm_interval_seconds_min": DEFAULT_SETTINGS["comment_dm_interval_seconds_min"],
        "comment_dm_interval_seconds_max": DEFAULT_SETTINGS["comment_dm_interval_seconds_max"],
        "comment_dm_percentage": DEFAULT_SETTINGS["comment_dm_percentage"],
        "follow_per_day": DEFAULT_SETTINGS["follow_per_day"],
        "dm_per_day": DEFAULT_SETTINGS["dm_per_day"],
        "batch_cooldown_minutes": DEFAULT_SETTINGS["batch_cooldown_minutes"],
    }
    base.update(extra)
    return base


def _round_mode_auto_payload():
    payload = build_auto_task_payload_like_frontend()
    payload["scope"]["repeat_mode"] = "round"
    payload["scope"]["round_target_count"] = 20
    payload["scope"]["max_rounds"] = 3
    return payload


def _kuaishou_auto_payload():
    payload = build_auto_task_payload_like_frontend()
    payload["platform"] = "kuaishou"
    payload["agent_strategy"] = "skill-flow-kuaishou"
    payload["scope"]["publish_time_range"] = "unlimited"
    return payload


def _minimal_auto_payload():
    """仅必填字段 + 最简评估。"""
    return {
        "intent": "keyword_auto",
        "name": "最简自动获客",
        "platform": "douyin",
        "scope": {"keyword": "健身房", "target_count": 10},
        "evaluation": {"accept_description": "有健身意向"},
        "correlation": {
            "external_system": "huoke_local",
            "external_task_id": "minimal-auto",
            "idempotency_key": "minimal-auto",
        },
        "agent_strategy": "skill-flow-douyin",
    }


def _rich_evaluation_manual_payload():
    payload = build_manual_task_payload_like_frontend()
    payload["evaluation"] = {
        "template_id": "custom",
        "target_customer": "装修业主",
        "accept_description": "询价、预约量房",
        "reject_description": "同行广告",
        "positive_examples": ["想了解一下报价"],
        "negative_examples": ["我们是装修公司"],
        "reject_signals": ["招聘", "加盟"],
        "precise_threshold": 0.85,
        "outreach_threshold": 0.65,
    }
    return payload


FORM_VARIANTS: list[tuple[str, callable, dict[str, Any]]] = [
    ("auto_basic", build_auto_task_payload_like_frontend, {"intent": "keyword_auto", "first_crawl": "crawl_keyword"}),
    ("auto_round_mode", _round_mode_auto_payload, {"intent": "keyword_auto", "first_crawl": "crawl_keyword", "has_round": True}),
    ("auto_xhs", build_xhs_auto_payload, {"intent": "keyword_auto", "first_crawl": "crawl_keyword", "platform": "xiaohongshu"}),
    ("manual_xhs", build_xhs_manual_payload, {"intent": "single_video", "first_crawl": "crawl_content_url", "platform": "xiaohongshu"}),
    ("account_home_xhs", build_xhs_account_home_payload, {"intent": "account_home", "first_crawl": "crawl_profile", "platform": "xiaohongshu"}),
    ("auto_kuaishou_unlimited", _kuaishou_auto_payload, {"intent": "keyword_auto", "first_crawl": "crawl_keyword", "platform": "kuaishou"}),
    ("auto_minimal", _minimal_auto_payload, {"intent": "keyword_auto", "first_crawl": "crawl_keyword"}),
    ("manual_single_video", build_manual_task_payload_like_frontend, {"intent": "single_video", "first_crawl": "crawl_content_url"}),
    ("manual_rich_eval", _rich_evaluation_manual_payload, {"intent": "single_video", "first_crawl": "crawl_content_url"}),
    ("account_home", build_account_home_payload_like_frontend, {"intent": "account_home", "first_crawl": "crawl_profile"}),
]

INVALID_VARIANTS: list[tuple[str, callable, str]] = [
    ("auto_missing_keyword", lambda: {**build_auto_task_payload_like_frontend(), "scope": {"target_count": 10}}, "scope"),
    (
        "manual_missing_url",
        lambda: {
            "intent": "single_video",
            "name": "缺URL",
            "platform": "douyin",
            "scope": {"comment_days": 3},
            "correlation": {"external_task_id": "bad-manual", "idempotency_key": "bad-manual"},
        },
        "scope",
    ),
]


def _unique_payload(builder, tag: str) -> dict:
    payload = copy.deepcopy(builder())
    token = f"audit-{tag}-{uuid.uuid4().hex[:8]}"
    correlation = dict(payload.get("correlation") or {})
    correlation["external_task_id"] = token
    correlation["idempotency_key"] = token
    payload["correlation"] = correlation
    payload["auto_execute"] = False
    return payload


def _step_actions(steps: list[dict]) -> list[str]:
    return [str(row.get("action") or "") for row in steps if isinstance(row, dict)]


def _classify_action(action: str) -> str:
    if action in CRAWL_ACTIONS:
        return "crawl"
    if action == "evaluate_leads":
        return "evaluate"
    if action == "query_stats":
        return "stats"
    if action in OUTREACH_ACTIONS:
        return "outreach"
    if action == "complete":
        return "complete"
    return "other"


def audit_execution_plan(plan: dict[str, Any], *, expected_first_crawl: str) -> list[str]:
    """返回计划不合理之处列表；空列表表示通过审计。"""
    issues: list[str] = []
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["执行计划无步骤"]

    actions = _step_actions(steps)
    if actions[0] != expected_first_crawl:
        issues.append(f"首步应为 {expected_first_crawl}，实际为 {actions[0]}")

    # 流水线阶段顺序
    phases = [_classify_action(a) for a in actions]
    phase_indices = {p: i for i, p in enumerate(phases)}
    for i, phase in enumerate(PIPELINE_ORDER):
        if phase not in phase_indices:
            if phase == "outreach":
                continue  # 触达步可能因配置为空
            issues.append(f"缺少阶段: {phase}")
            continue
        for earlier in PIPELINE_ORDER[:i]:
            if earlier in phase_indices and phase_indices[earlier] > phase_indices[phase]:
                issues.append(f"阶段顺序错误: {earlier} 应在 {phase} 之前")

    if "evaluate_leads" not in actions:
        issues.append("缺少 LLM 评估步骤 evaluate_leads")
    if "query_stats" not in actions:
        issues.append("缺少配额同步步骤 query_stats")
    if actions[-1] != "complete":
        issues.append(f"末步应为 complete，实际为 {actions[-1]}")

    orders = [int(row.get("order") or 0) for row in steps if isinstance(row, dict)]
    if orders != sorted(orders):
        issues.append("步骤 order 未单调递增")
    if len(set(orders)) != len(orders):
        issues.append("步骤 order 存在重复")

    crawl_step = next((s for s in steps if s.get("action") in CRAWL_ACTIONS), None)
    if crawl_step and not crawl_step.get("required"):
        issues.append("抓取步骤应标记 required=True")

    eval_step = next((s for s in steps if s.get("action") == "evaluate_leads"), None)
    if eval_step and not eval_step.get("required"):
        issues.append("评估步骤应标记 required=True")

    for step in steps:
        action = str(step.get("action") or "")
        if action in OUTREACH_ACTIONS and step.get("repeat_until") != "quota_or_no_targets":
            issues.append(f"触达步骤 {action} 应设置 repeat_until=quota_or_no_targets")

    if plan.get("pipeline") in {None, ""}:
        issues.append("计划缺少 pipeline 标识")

    return issues


def _tactical_from_macro(orch: dict) -> list[dict]:
    for step in orch.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("id") in {"plan", "act"}:
            sub = step.get("sub_steps")
            if isinstance(sub, list) and sub:
                return sub
    return []


def _preflight_tactical_steps(body: dict) -> list[dict]:
    orch = body.get("orchestration") or {}
    return orch.get("steps") or []


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,expect", FORM_VARIANTS)
async def test_form_variant_preflight_create_orchestration_audit(
    flow_client,
    variant_name,
    builder,
    expect,
):
    """每种表单：预检通过 → 创建 pending → 审计宏观/战术编排（不执行）。"""
    client, _settings, svc = flow_client
    payload = _unique_payload(builder, variant_name)

    preflight = client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert preflight.status_code == 200, preflight.text
    pf_body = preflight.json()
    assert pf_body["ready"] is True, pf_body
    assert pf_body["blocking_count"] == 0
    blocking = [c for c in pf_body.get("checks", []) if c.get("blocking")]
    assert not blocking, blocking

    pf_actions = _step_actions(_preflight_tactical_steps(pf_body))
    assert expect["first_crawl"] in pf_actions
    assert "evaluate_leads" in pf_actions

    create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert create.status_code == 200, create.text
    job_body = create.json()
    assert job_body["status"] == "pending"
    assert job_body["auto_execute"] is False

    result = job_body.get("result") or {}
    assert result.get("execution_mode") == "supervisor"
    orch = result.get("orchestration") or {}
    assert orch.get("source") == "supervisor"
    assert orch.get("execution_mode") == "skill_flow"

    macro_ids = {s.get("id") for s in orch.get("steps") or [] if isinstance(s, dict)}
    assert {"understand", "observe", "plan", "act", "track", "dream"}.issubset(macro_ids)

    brief_raw = orch.get("task_brief") or {}
    brief = TaskBrief.model_validate(brief_raw)
    exec_plan = build_supervisor_execution_plan(brief, {})
    issues = audit_execution_plan(exec_plan, expected_first_crawl=expect["first_crawl"])
    assert not issues, f"[{variant_name}] 执行计划审计失败: {issues}"

    macro_tactical = _tactical_from_macro(orch)
    assert macro_tactical, f"[{variant_name}] 宏观编排 plan/act 缺少 sub_steps"
    macro_actions = _step_actions(macro_tactical)
    rebuilt_actions = _step_actions(exec_plan.get("steps") or [])
    assert macro_actions == rebuilt_actions, (
        f"[{variant_name}] 宏观 sub_steps 与战术计划不一致:\n"
        f"  macro={macro_actions}\n  rebuilt={rebuilt_actions}"
    )

    pf_macro_actions = _step_actions(_preflight_tactical_steps(pf_body))
    assert pf_macro_actions == rebuilt_actions, (
        f"[{variant_name}] 预检编排与创建后编排不一致:\n"
        f"  preflight={pf_macro_actions}\n  created={rebuilt_actions}"
    )

    if expect.get("has_round"):
        summary = orch.get("input_summary") or {}
        assert summary.get("repeat_mode") == "round"
        assert summary.get("round_target_count") == 20
        assert summary.get("max_rounds") == 3

    if expect.get("platform"):
        assert brief.platform == expect["platform"]

    loaded = svc.get_job("default", job_body["job_id"])
    assert loaded is not None
    assert loaded.status == "pending"
    assert loaded.correlation.get("external_task_id") == payload["correlation"]["external_task_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name,builder,check_id", INVALID_VARIANTS)
async def test_invalid_form_blocked_at_preflight(flow_client, variant_name, builder, check_id):
    client, _settings, _svc = flow_client
    payload = _unique_payload(builder, variant_name)

    resp = client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    failed = [c for c in body.get("checks", []) if c.get("id") == check_id]
    assert failed and failed[0]["status"] == "error"


@pytest.mark.asyncio
async def test_preflight_evaluation_accept_preview_ready(flow_client):
    """评估接受规则在预检阶段应生成可读的 accept_preview。"""
    client, _settings, _svc = flow_client
    payload = _unique_payload(_rich_evaluation_manual_payload, "eval-preview")

    resp = client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    evaluation = body.get("evaluation") or {}
    assert evaluation.get("ready") is True
    assert evaluation.get("llm_configured") is True
    assert evaluation.get("accept_preview")
    assert "询价" in evaluation["accept_preview"] or "预约" in evaluation["accept_preview"]


@pytest.mark.asyncio
async def test_create_does_not_enqueue_when_auto_execute_false(flow_client):
    """编排完成后保持 pending，不自动入队执行。"""
    client, _settings, svc = flow_client
    payload = _unique_payload(build_auto_task_payload_like_frontend, "no-queue")

    create = client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    job_id = create.json()["job_id"]
    assert create.json()["status"] == "pending"
    assert job_id not in svc._running_jobs

    detail = client.get(f"/api/agent/jobs/{job_id}", headers=API_HEADERS)
    assert detail.json()["status"] == "pending"


def test_audit_catches_bad_plan_order():
    """审计器能识别步骤顺序错误。"""
    bad_plan = {
        "pipeline": "skill_flow",
        "steps": [
            {"order": 1, "action": "evaluate_leads", "required": True},
            {"order": 2, "action": "crawl_keyword", "required": True},
            {"order": 3, "action": "query_stats", "required": True},
            {"order": 4, "action": "complete", "required": True},
        ],
    }
    issues = audit_execution_plan(bad_plan, expected_first_crawl="crawl_keyword")
    assert any("首步" in i or "顺序" in i for i in issues)
