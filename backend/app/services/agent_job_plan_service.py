from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.services.agent_strategy import parse_strategy_from_payload
from app.services.task_brief_service import (
    TaskBrief,
    _extract_json_from_message,
    _finalize_brief,
    enrich_brief_from_skill_message,
    enrich_brief_from_task_payload,
    generate_task_brief,
    is_skill_flow_brief,
)
from app.services.task_execution_plan import build_supervisor_execution_plan
from app.services.task_round_service import max_rounds_from_brief, round_loop_enabled, round_target_from_brief

SUPERVISOR_STEPS: list[dict[str, str]] = [
    {"id": "understand", "stage": "understand", "action": "大模型理解任务并生成 task_brief.md"},
    {"id": "observe", "stage": "observe", "action": "读取简报 + 查询互动台账与进度快照"},
    {"id": "plan", "stage": "plan", "action": "Supervisor LLM 战术决策下一动作"},
    {"id": "act", "stage": "act", "action": "调用确定性 Skill / Pipeline 执行"},
    {"id": "track", "stage": "track", "action": "记录结果并更新数据快照"},
    {"id": "dream", "stage": "dream", "action": "复盘经验写回 Agent 记忆"},
]

PLAN_DRIVEN_STEPS: list[dict[str, str]] = [
    {"id": "understand", "stage": "understand", "action": "解析任务 JSON / 自然语言，生成 task_brief.md"},
    {"id": "observe", "stage": "observe", "action": "读取简报 + 互动台账快照（配额 / 线索进度）"},
    {"id": "plan", "stage": "plan", "action": "按计划表推进下一战术步（计划驱动，不用 LLM）"},
    {"id": "act", "stage": "act", "action": "Skill 独立执行：抓取入库 → 规则匹配触达"},
    {"id": "track", "stage": "track", "action": "写入触达台账，更新 leads_collected；配额用尽则挂起到次日"},
    {"id": "dream", "stage": "dream", "action": "跳过 Agent 记忆复盘"},
]


def _step(
    *,
    step_id: str,
    stage: str,
    action: str,
    capability: str = "",
    status: str = "pending",
    order: int,
    sub_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": step_id,
        "stage": stage,
        "action": action,
        "capability": capability,
        "status": status,
        "order": order,
    }
    if sub_steps:
        row["sub_steps"] = sub_steps
    return row


def _macro_steps_for_brief(brief: TaskBrief) -> list[dict[str, str]]:
    if is_skill_flow_brief(brief) or bool(brief.goals.get("supervisor_plan_only")):
        return PLAN_DRIVEN_STEPS
    return SUPERVISOR_STEPS


def _tactical_sub_steps(brief: TaskBrief) -> list[dict[str, Any]]:
    plan = build_supervisor_execution_plan(brief, {})
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return []
    return [
        {
            "action": str(row.get("action") or ""),
            "label": str(row.get("label") or row.get("action") or ""),
            "order": int(row.get("order") or idx + 1),
            "repeat_until": row.get("repeat_until"),
        }
        for idx, row in enumerate(steps)
        if isinstance(row, dict)
    ]


def _brief_to_input_summary(brief: TaskBrief) -> dict[str, Any]:
    summary = {
        "task_name": brief.title,
        "keyword": brief.keyword,
        "platform": brief.platform,
        "region": brief.region,
        "target_leads": brief.goals.get("target_leads"),
        "comment_days": brief.goals.get("comment_days"),
        "success_criteria": brief.success_criteria,
        "agent_strategy": brief.agent_strategy,
        "execution_mode": brief.goals.get("execution_mode"),
    }
    if round_loop_enabled(brief):
        summary.update(
            {
                "repeat_mode": "round",
                "round_target_count": round_target_from_brief(brief),
                "max_rounds": max_rounds_from_brief(brief),
            }
        )
    return {k: v for k, v in summary.items() if v is not None and v != ""}


def _plan_from_brief(brief: TaskBrief, *, unmapped_fields: list[str] | None = None) -> dict[str, Any]:
    plan_driven = is_skill_flow_brief(brief) or bool(brief.goals.get("supervisor_plan_only"))
    tactical = _tactical_sub_steps(brief) if plan_driven else []
    macro_steps = _macro_steps_for_brief(brief)

    steps: list[dict[str, Any]] = []
    for idx, item in enumerate(macro_steps):
        sub_steps = tactical if plan_driven and item["id"] in {"plan", "act"} else None
        steps.append(
            _step(
                step_id=item["id"],
                stage=item["stage"],
                action=item["action"],
                capability="internal.supervisor" if item["id"] in {"observe", "plan", "act", "track"} else "",
                status="completed" if item["id"] == "understand" else ("skipped" if plan_driven and item["id"] == "dream" else "pending"),
                order=idx + 1,
                sub_steps=sub_steps,
            )
        )

    method = "llm" if brief.llm_available else "rule"
    confidence_pct = f"{brief.confidence:.0%}"
    if plan_driven:
        execution_note = (
            f"计划驱动 · 策略 `{brief.agent_strategy or 'skill-flow-douyin'}`；"
            f"已由大模型生成任务简报（置信度 {confidence_pct}）。"
            "启动后 Supervisor **按计划逐步执行**（抓取入库 → 同步配额 → 独立 reply/dm/follow 消费已入库数据），"
            "**不使用 LLM 决策**。"
        )
        if tactical:
            labels = " → ".join(s["label"] for s in tactical[:4])
            execution_note += f" 战术链：{labels}。"
    elif brief.llm_available:
        execution_note = (
            f"已由大模型生成任务简报（置信度 {confidence_pct}）；"
            "启动后 Supervisor 按战术计划逐步执行，禁止跳步。"
        )
    else:
        execution_note = (
            "大模型未配置，已使用规则回退生成简报；"
            "配置 DEEPSEEK_API_KEY 后重新创建可获得 LLM 简报。"
        )

    exec_plan = build_supervisor_execution_plan(brief, {}) if plan_driven else None

    return {
        "source": "supervisor",
        "template_id": brief.agent_strategy if plan_driven else None,
        "template_name": "计划驱动（Skill 分步）" if plan_driven else "Supervisor 混合架构",
        "execution_mode": "skill_flow" if is_skill_flow_brief(brief) else "supervisor",
        "compile_method": method,
        "llm_compiled": brief.llm_available,
        "llm_fallback": brief.llm_fallback,
        "is_preview": not brief.llm_available,
        "confidence": brief.confidence,
        "reasoning": brief.reasoning,
        "execution_note": execution_note,
        "task_brief": brief.model_dump(),
        "input_summary": _brief_to_input_summary(brief),
        "steps": steps,
        "tactical_plan": exec_plan,
        "unmapped_fields": unmapped_fields or [],
    }


def _attach_source_input(
    plan: dict[str, Any],
    *,
    message: str,
    payload: dict[str, Any] | None,
    agent_strategy: str | None = None,
) -> dict[str, Any]:
    text = (message or "").strip()
    if text:
        plan["source_message"] = text
    source_payload: dict[str, Any] = dict(payload) if isinstance(payload, dict) else {}
    if agent_strategy and not source_payload.get("agent_strategy"):
        source_payload["agent_strategy"] = agent_strategy
    if source_payload:
        plan["source_payload"] = source_payload
    return plan


async def build_orchestration_plan(
    message: str,
    *,
    settings: Settings,
    tenant_id: str,
    provider: str = "deepseek",
    agent_strategy: str | None = None,
) -> dict[str, Any]:
    """唯一编排入口：生成 task_brief + Supervisor 循环计划 + 专用智能体绑定。"""
    text = (message or "").strip()
    payload = _extract_json_from_message(text)
    strategy_id = agent_strategy or parse_strategy_from_payload(payload, platform="douyin")
    brief = await generate_task_brief(
        message,
        settings=settings,
        tenant_id=tenant_id,
        provider=provider,
        agent_strategy=strategy_id,
    )
    brief = enrich_brief_from_skill_message(brief, text)
    brief, unmapped = enrich_brief_from_task_payload(brief, payload)
    brief = _finalize_brief(brief, agent_strategy=strategy_id)
    plan = _plan_from_brief(brief, unmapped_fields=unmapped)
    from app.services.dedicated_agent.service import DedicatedAgentService

    DedicatedAgentService(settings).attach_to_orchestration_plan(tenant_id, brief, plan)
    return _attach_source_input(
        plan,
        message=text,
        payload=payload if isinstance(payload, dict) else None,
        agent_strategy=strategy_id,
    )


def sync_orchestration_status(
    orchestration: dict[str, Any],
    *,
    job_stage: str,
    job_status: str,
    job_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.services.task_execution_plan import build_execution_note, build_suspend_brief

    steps = orchestration.get("steps")
    if not isinstance(steps, list) or not steps:
        return orchestration

    stage_ids = [str(item.get("stage") or item.get("id") or "") for item in steps]
    current_idx = stage_ids.index(job_stage) if job_stage in stage_ids else -1

    state = {}
    if isinstance(job_result, dict):
        raw_state = job_result.get("supervisor_state")
        if isinstance(raw_state, dict):
            state = raw_state

    if job_status == "pending" and state.get("suspended"):
        crawl_failed = int(state.get("crawl_failures") or 0) >= 1
        crawl_done = bool(state.get("crawl_done"))
        stats_synced = bool(state.get("stats_synced"))
        for step in steps:
            if step.get("status") == "skipped":
                continue
            sid = str(step.get("id") or step.get("stage") or "")
            if sid == "understand":
                step["status"] = "completed"
            elif sid in {"observe", "plan"}:
                step["status"] = "completed"
            elif sid == "act":
                if crawl_failed and not crawl_done:
                    step["status"] = "failed"
                elif crawl_done:
                    step["status"] = "completed"
                else:
                    step["status"] = "pending"
            elif sid == "track":
                step["status"] = "completed" if stats_synced else "pending"
            elif sid == "dream":
                step["status"] = "skipped"
        orchestration["steps"] = steps
        note = build_execution_note(job_status=job_status, job_stage=job_stage, job_result=job_result)
        if note:
            orchestration["execution_note"] = note
        suspend = build_suspend_brief(
            state,
            job_result,
            orchestration.get("task_brief") if isinstance(orchestration.get("task_brief"), dict) else None,
        )
        if suspend:
            orchestration["suspend_brief"] = suspend
        return orchestration

    for idx, step in enumerate(steps):
        if step.get("status") == "skipped":
            continue
        if job_status == "completed":
            if step.get("status") != "skipped":
                step["status"] = "completed"
        elif job_status in {"failed", "dead_letter", "cancelled"}:
            if current_idx < 0:
                step["status"] = "pending" if step.get("status") != "skipped" else "skipped"
            elif idx < current_idx:
                step["status"] = "completed" if step.get("status") != "skipped" else "skipped"
            elif idx == current_idx:
                step["status"] = "failed" if job_status != "cancelled" else "cancelled"
            else:
                step["status"] = "pending" if step.get("status") != "skipped" else "skipped"
        elif job_status in {"running", "retrying"}:
            if idx < current_idx:
                step["status"] = "completed" if step.get("status") != "skipped" else "skipped"
            elif idx == current_idx:
                step["status"] = "running"
            else:
                step["status"] = "pending" if step.get("status") != "skipped" else "skipped"
        else:
            if step.get("id") == "understand":
                step["status"] = "completed"
            elif step.get("status") != "skipped":
                step["status"] = "pending"

    orchestration["steps"] = steps
    note = build_execution_note(job_status=job_status, job_stage=job_stage, job_result=job_result)
    if note:
        orchestration["execution_note"] = note
    state_for_suspend = {}
    if isinstance(job_result, dict):
        raw_state = job_result.get("supervisor_state")
        if isinstance(raw_state, dict):
            state_for_suspend = raw_state
    suspend = build_suspend_brief(
        state_for_suspend,
        job_result,
        orchestration.get("task_brief") if isinstance(orchestration.get("task_brief"), dict) else None,
    )
    if suspend:
        orchestration["suspend_brief"] = suspend
    else:
        orchestration.pop("suspend_brief", None)
    return orchestration
