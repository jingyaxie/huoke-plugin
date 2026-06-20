from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.task_brief_service import TaskBrief, is_skill_flow_brief
from app.services.standalone_browse_adapter import (
    is_standalone_browse_brief,
    build_standalone_execution_plan,
    upgrade_standalone_execution_plan,
    _standalone_plan_needs_upgrade,
)
from app.services.manual_acquisition_service import build_manual_acquisition_plan, manual_acquisition_mode
from app.services.task_round_service import (
    effective_leads_collected,
    effective_leads_qualified,
    effective_supervisor_goal_count,
    effective_target_leads,
    goal_reached_for_current_round,
    round_loop_enabled,
    uses_qualified_leads_goal,
)
from app.services.task_skill_playbook import skill_id_for_supervisor_action
from app.services.supervisor_crawl_helpers import (
    CRAWL_SUPERVISOR_ACTIONS,
    OUTREACH_LOOP_ACTIONS,
    apply_crawl_video_limit_aliases,
    build_url_revisit_decision,
    effective_crawl_video_limit,
    prepare_plan_recrawl,
    reset_crawl_evaluate_gate_state,
    reset_plan_evaluation_state,
    should_resume_crawl_on_no_match,
    infer_suspend_next_action as infer_skill_flow_suspend_next_action,
)
from app.services.supervisor_outreach import (
    next_outreach_action_from_brief,
    outreach_bucket_can_do,
    outreach_priority_from_brief,
    outreach_quotas_exhausted,
)

_OUTREACH_LABELS = {
    "reply": "回复评论（消费已入库数据，按规则匹配）",
    "dm": "私信用户（消费已入库数据，按规则匹配）",
    "follow": "关注用户（消费已入库数据，按规则匹配）",
}


def default_crawl_video_limit(brief: TaskBrief) -> int:
    return effective_crawl_video_limit(brief=brief)


def _outreach_steps(brief: TaskBrief, *, start_order: int) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    order = start_order
    for action in outreach_priority_from_brief(brief):
        steps.append(
            {
                "id": action,
                "order": order,
                "action": action,
                "label": _OUTREACH_LABELS.get(action, action),
                "status": "pending",
                "required": False,
                "repeat_until": "quota_or_no_targets",
                "params": {"keyword": brief.keyword or ""},
            }
        )
        order += 1
    return steps


def _crawl_limit_suffix(video_limit: int) -> str:
    return f"；最多 {video_limit} 个视频"


def _crawl_step_params(brief: TaskBrief, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.services.supervisor_crawl_helpers import build_crawl_day_params

    params: dict[str, Any] = {
        "keyword": brief.keyword or "",
        "region": brief.region,
        **build_crawl_day_params(brief),
    }
    video_limit = default_crawl_video_limit(brief)
    apply_crawl_video_limit_aliases(params, video_limit)
    if is_skill_flow_brief(brief):
        params["ui_search_only"] = True
        params["search_url_first"] = False
    if extra:
        params.update(extra)
    return params


def _plan_has_outreach_steps(plan: dict[str, Any]) -> bool:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return False
    return any(
        isinstance(step, dict) and str(step.get("action") or "") in OUTREACH_LOOP_ACTIONS
        for step in steps
    )


def ensure_supervisor_execution_plan(brief: TaskBrief, state: dict[str, Any]) -> dict[str, Any]:
    """生成或升级战术计划（skill_flow 旧计划补触达步）。"""
    plan = state.get("execution_plan")
    if is_standalone_browse_brief(brief):
        if not isinstance(plan, dict) or plan.get("pipeline") != "standalone_browse":
            return build_standalone_execution_plan(brief, state)
        if _standalone_plan_needs_upgrade(plan):
            return upgrade_standalone_execution_plan(plan, brief, state)
        return sync_supervisor_plan_from_state(plan, state)
    if is_skill_flow_brief(brief):
        if not isinstance(plan, dict) or not _plan_has_outreach_steps(plan):
            return build_supervisor_execution_plan(brief, state)
        return sync_supervisor_plan_from_state(plan, state)
    if not isinstance(plan, dict):
        return build_supervisor_execution_plan(brief, state)
    return sync_supervisor_plan_from_state(plan, state)


def build_supervisor_execution_plan(brief: TaskBrief, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """根据任务简报生成 Supervisor 战术执行计划（有序、不可跳步）。"""
    state = state or {}
    if is_standalone_browse_brief(brief):
        return build_standalone_execution_plan(brief, state)
    manual_plan = build_manual_acquisition_plan(brief, state)
    if manual_plan is not None:
        return manual_plan
    keyword = str(brief.keyword or "").strip() or "关键词"
    target = int(brief.goals.get("target_leads") or 0)
    video_limit = default_crawl_video_limit(brief)
    limit_suffix = _crawl_limit_suffix(video_limit)
    reply_template = str(brief.constraints.get("reply_template") or brief.goals.get("reply_template") or "").strip()
    inline_ui = bool(brief.goals.get("inline_ui_outreach", False))
    execution_mode = str(brief.goals.get("execution_mode") or "")
    if execution_mode == "skill_flow":
        crawl_label = f"搜索框输入「{keyword}」→ 监听浏览器请求抓评论入库{limit_suffix}"
        outreach_steps = _outreach_steps(brief, start_order=4)
        outreach_names = " → ".join(str(s["action"]) for s in outreach_steps) or "无触达"
        steps: list[dict[str, Any]] = [
            {
                "id": "crawl",
                "order": 1,
                "action": "crawl_keyword",
                "label": crawl_label,
                "status": "completed" if state.get("crawl_done") else "pending",
                "required": True,
                "params": _crawl_step_params(brief),
            },
            {
                "id": "evaluate",
                "order": 2,
                "action": "evaluate_leads",
                "label": "LLM 评估入库评论是否符合线索标准",
                "status": "completed" if state.get("evaluation_done") else "pending",
                "required": True,
                "params": {"platform": brief.platform or "douyin"},
            },
            {
                "id": "sync_stats",
                "order": 3,
                "action": "query_stats",
                "label": "同步今日 reply/follow/dm 触达配额",
                "status": "completed" if state.get("stats_synced") else "pending",
                "required": True,
                "params": {"platform": brief.platform or "douyin"},
            },
            *outreach_steps,
            {
                "id": "finish",
                "order": 4 + len(outreach_steps),
                "action": "complete",
                "label": f"触达步骤完成后结束（目标线索 ≥ {target or '配置'}）",
                "status": "pending",
                "required": True,
                "params": {},
            },
        ]
        summary = (
            f"【{brief.title or keyword}】类人分步："
            f" ①抓取入库 → ②LLM 评估 → ③同步配额 → ④独立触达（{outreach_names}）→ ⑤结束"
        )
        return {
            "summary": summary,
            "steps": steps,
            "current_index": _resolve_current_index(steps),
            "version": 2,
            "pipeline": "skill_flow",
        }
    if inline_ui:
        crawl_label = (
            f"搜索「{keyword}」→ 浏览评论侧栏 → **在 UI 上直接回复/私信/关注**（不必等入库）"
            f"{limit_suffix}"
        )
    else:
        crawl_label = f"抓取「{keyword}」相关评论{limit_suffix}"
    steps: list[dict[str, Any]] = [
        {
            "id": "crawl",
            "order": 1,
            "action": "crawl_keyword",
            "label": crawl_label,
            "status": "completed" if state.get("crawl_done") else "pending",
            "required": True,
            "params": _crawl_step_params(
                brief,
                extra={
                    "inline_ui_outreach": inline_ui,
                    "reply_template": reply_template or None,
                },
            ),
        },
        {
            "id": "sync_stats",
            "order": 2,
            "action": "query_stats",
            "label": "同步今日 reply/follow/dm 触达配额",
            "status": "completed" if state.get("stats_synced") else "pending",
            "required": True,
            "params": {"platform": brief.platform or "douyin"},
        },
        {
            "id": "finish",
            "order": 3,
            "action": "complete",
            "label": "战术步骤全部完成后结束（须已达到目标线索）",
            "status": "pending",
            "required": True,
            "params": {},
        },
    ]

    summary = (
        f"【{brief.title or keyword}】"
        f" ①搜索+浏览+UI触达（同屏操作） → ②同步配额 → ③结束；"
        f"评论/私信/关注均在界面上点击输入，禁止等入库后再触达。"
    )
    return {
        "summary": summary,
        "steps": steps,
        "current_index": _resolve_current_index(steps),
        "version": 1,
    }


def _resolve_current_index(steps: list[dict[str, Any]]) -> int:
    for idx, step in enumerate(steps):
        if step.get("status") not in {"completed", "skipped"}:
            return idx
    return max(len(steps) - 1, 0)


def _step_by_index(plan: dict[str, Any], index: int) -> dict[str, Any] | None:
    steps = plan.get("steps")
    if not isinstance(steps, list) or index < 0 or index >= len(steps):
        return None
    row = steps[index]
    return row if isinstance(row, dict) else None


def sync_supervisor_plan_from_state(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """用 supervisor_state 回填计划步骤状态。"""
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return plan
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "")
        if action in CRAWL_SUPERVISOR_ACTIONS and state.get("crawl_done"):
            step["status"] = "completed" if not state.get("crawl_failures") else step.get("status")
        if action == "evaluate_leads" and state.get("evaluation_done"):
            step["status"] = "completed"
        if action == "query_stats" and state.get("stats_synced"):
            step["status"] = "completed"
        if action in {"reply", "dm", "follow", "outreach"}:
            target = int(state.get("_plan_target_leads") or 0)
            leads = int(state.get("leads_collected") or 0)
            if target > 0 and leads >= target:
                step["status"] = "completed"
            elif action in OUTREACH_LOOP_ACTIONS and str(step.get("repeat_until") or "") == "quota_or_no_targets":
                last_stats = state.get("last_stats") if isinstance(state.get("last_stats"), dict) else {}
                bucket = last_stats.get(action) if isinstance(last_stats.get(action), dict) else {}
                if last_stats and not outreach_bucket_can_do(bucket):
                    step["status"] = "completed"
    plan["current_index"] = _resolve_current_index(steps)
    return plan


def reset_supervisor_state_for_manual_retry(
    state: dict[str, Any],
    plan: dict[str, Any] | None = None,
    *,
    brief: TaskBrief | None = None,
) -> dict[str, Any]:
    """手动继续：清除挂起标记，并重置失败抓取步骤以便重试。"""
    state.pop("suspended", None)
    state.pop("resume_at", None)
    state.pop("wake_reason", None)
    state["stale_cycles"] = 0
    state["_repeat_action_count"] = 0
    state.pop("_repeat_action", None)
    state.pop("completion_outcome", None)
    reset_crawl_evaluate_gate_state(state)

    from app.services.supervisor_crawl_helpers import prepare_plan_recrawl

    force_recrawl = (
        brief is not None
        and is_skill_flow_brief(brief)
        and bool(brief.goals.get("force_refresh", True))
    )
    plan_incomplete = str(state.get("completion_outcome") or "") == "plan_incomplete"
    outreach_only_resume = (
        plan_incomplete
        and bool(state.get("crawl_done"))
        and brief is not None
        and is_skill_flow_brief(brief)
        and not force_recrawl
    )
    if outreach_only_resume and isinstance(plan, dict):
        state.pop("completion_outcome", None)
        steps = plan.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                action = str(step.get("action") or "")
                if action in OUTREACH_LOOP_ACTIONS or action == "complete":
                    step["status"] = "pending"
            plan["current_index"] = _resolve_current_index(steps)
            state["execution_plan"] = plan
        return state

    crawl_failed = (
        int(state.get("crawl_failures") or 0) >= 1
        or not state.get("crawl_done")
        or (plan_incomplete and not outreach_only_resume)
        or force_recrawl
    )
    if not crawl_failed:
        return state

    state["crawl_failures"] = 0
    state.pop("crawl_done", None)
    state.pop("visible_crawl_done", None)
    state.pop("crawl_risk_blocked", None)
    state.pop("stats_synced", None)
    state.pop("last_action", None)

    if force_recrawl and brief is not None:
        prepare_plan_recrawl(state, plan, brief=brief)
        return state

    if not isinstance(plan, dict):
        return state

    steps = plan.get("steps")
    if not isinstance(steps, list):
        return state

    retry_from = 0
    for idx, step in enumerate(steps):
        if isinstance(step, dict) and str(step.get("status") or "") == "failed":
            retry_from = idx
            break

    reset_eval = False
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "")
        if idx >= retry_from and action not in {"complete"}:
            step["status"] = "pending"
            if action in CRAWL_SUPERVISOR_ACTIONS or action == "evaluate_leads":
                reset_eval = True

    if reset_eval:
        reset_plan_evaluation_state(state, plan)

    plan["current_index"] = _resolve_current_index(steps)
    state["execution_plan"] = plan
    return state


def _plan_step_for_action(
    steps: list[Any],
    action: str,
    current_index: int,
) -> tuple[dict[str, Any] | None, int]:
    """按 action 定位计划步骤，避免 current_index 指向其它步骤时误标完成。"""
    current: dict[str, Any] | None = None
    if 0 <= current_index < len(steps) and isinstance(steps[current_index], dict):
        current = steps[current_index]
    if current is not None and str(current.get("action") or "") == action:
        return current, current_index
    for idx, row in enumerate(steps):
        if not isinstance(row, dict):
            continue
        if str(row.get("action") or "") != action:
            continue
        if row.get("status") in {"pending", "in_progress"}:
            return row, idx
    for idx, row in enumerate(steps):
        if isinstance(row, dict) and str(row.get("action") or "") == action:
            return row, idx
    if action in OUTREACH_LOOP_ACTIONS:
        for idx, row in enumerate(steps):
            if (
                isinstance(row, dict)
                and str(row.get("id") or "") == "outreach"
                and row.get("status") in {"pending", "in_progress"}
            ):
                return row, idx
    return None, current_index


def advance_supervisor_plan(
    plan: dict[str, Any],
    *,
    action: str,
    ok: bool,
    state: dict[str, Any],
    brief: TaskBrief,
) -> dict[str, Any]:
    """动作执行后更新计划进度。"""
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return plan
    index = int(plan.get("current_index") or 0)
    revisit_under_crawl = action == "crawl_content_url" and bool(state.get("_revisit_under_crawl_step"))
    if revisit_under_crawl:
        step, index = _plan_step_for_action(steps, "crawl_keyword", index)
    else:
        step, index = _plan_step_for_action(steps, action, index)
    if step is None:
        plan["current_index"] = _resolve_current_index(steps)
        return plan

    step_action = str(step.get("action") or "")
    if step_action != action and not (
        action in OUTREACH_LOOP_ACTIONS and str(step.get("id") or "") == "outreach"
    ):
        plan["current_index"] = _resolve_current_index(steps)
        return plan

    if not ok and action == "crawl_keyword" and step_action in OUTREACH_LOOP_ACTIONS:
        # 无匹配线索触发的续抓失败：勿把 reply/dm/follow 步标为 skipped 以免计划误进 complete
        plan["current_index"] = _resolve_current_index(steps)
        return plan

    if ok:
        repeat = str(step.get("repeat_until") or "")
        target = int(brief.goals.get("target_leads") or 0)
        state["_plan_target_leads"] = target
        last_stats = state.get("last_stats") if isinstance(state.get("last_stats"), dict) else {}
        if repeat == "quota_or_no_targets" and action in OUTREACH_LOOP_ACTIONS:
            bucket = last_stats.get(action) if isinstance(last_stats.get(action), dict) else {}
            if outreach_bucket_can_do(bucket):
                step["status"] = "in_progress"
            else:
                step["status"] = "completed"
        elif action == "reply" and repeat == "target_leads_or_quota":
            leads = int(state.get("leads_collected") or 0)
            if target > 0 and leads < target and not outreach_quotas_exhausted(last_stats, brief):
                step["status"] = "in_progress"
            else:
                step["status"] = "completed"
        elif action in OUTREACH_LOOP_ACTIONS and repeat == "target_leads_or_quota":
            leads = int(state.get("leads_collected") or 0)
            if target > 0 and leads < target and not outreach_quotas_exhausted(last_stats, brief):
                step["status"] = "in_progress"
            else:
                step["status"] = "completed"
        elif action == "outreach" and repeat == "target_leads_or_quota":
            leads = int(state.get("leads_collected") or 0)
            if target > 0 and leads < target and not outreach_quotas_exhausted(last_stats, brief):
                step["status"] = "in_progress"
            else:
                step["status"] = "completed"
        elif revisit_under_crawl:
            step["status"] = "in_progress"
        elif (
            action in CRAWL_SUPERVISOR_ACTIONS
            and is_standalone_browse_brief(brief)
            and not revisit_under_crawl
        ):
            target = int(brief.goals.get("target_leads") or state.get("_plan_target_leads") or 0)
            qualified = int(state.get("leads_qualified") or 0)
            if target > 0 and qualified < target and not state.get("crawl_search_exhausted"):
                step["status"] = "in_progress"
            else:
                step["status"] = "completed"
        else:
            step["status"] = "completed"
    else:
        if revisit_under_crawl and not ok:
            step["status"] = "in_progress"
        elif step.get("required"):
            step["status"] = "failed"
        elif action in OUTREACH_LOOP_ACTIONS:
            step["status"] = "completed"
        else:
            step["status"] = "skipped"

    if revisit_under_crawl:
        state.pop("_revisit_under_crawl_step", None)
        state.pop("_revisit_content_id", None)

    plan["current_index"] = _resolve_current_index(steps)
    return plan


def _maybe_recrawl_after_zero_qualified(
    brief: TaskBrief,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    stats: dict[str, Any] | None = None,
) -> bool:
    """评估后无精准线索且搜索列表仍有视频时，回退抓取步避免触达空转。"""
    if not state.get("evaluation_done"):
        return False
    if "leads_qualified" not in state:
        return False
    if int(state.get("leads_qualified") or 0) > 0:
        return False
    if not should_resume_crawl_on_no_match(brief, state, stats):
        return False
    prepare_plan_recrawl(state, plan, brief=brief)
    state.pop("evaluation_done", None)
    state.pop("leads_qualified", None)
    state["stale_cycles"] = 0
    steps = plan.get("steps")
    if isinstance(steps, list):
        for row in steps:
            if isinstance(row, dict) and str(row.get("action") or "") == "evaluate_leads":
                row["status"] = "pending"
    return True


def plan_driven_supervisor_decision(
    plan: dict[str, Any],
    brief: TaskBrief,
    state: dict[str, Any],
    *,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """按计划返回下一动作；计划已完成时返回 complete。"""
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return None

    index = int(plan.get("current_index") or 0)
    step = _step_by_index(plan, index)
    if step is None:
        return guard_supervisor_complete_decision(
            brief,
            state,
            {
                "action": "complete",
                "reasoning": "执行计划已全部完成",
                "params": {},
                "goal_progress": _goal_progress(brief, state),
                "plan_step_id": "finish",
            },
        )

    status = str(step.get("status") or "pending")
    action = str(step.get("action") or "")
    step_id = str(step.get("id") or "")

    if status == "failed":
        if action == "crawl_keyword":
            revisit = build_url_revisit_decision(
                brief,
                state,
                reasoning=f"【补抓】搜索失败，直接打开已发现视频补抓评论（跳过搜索框）",
                plan_step_id=step_id,
            )
            if revisit is not None:
                step["status"] = "in_progress"
                return revisit
        reason = f"计划步骤「{step.get('label') or step_id}」失败，挂起等待人工处理"
        err = str(state.get("last_crawl_error") or "").strip()
        if err and action in CRAWL_SUPERVISOR_ACTIONS and is_standalone_browse_brief(brief):
            reason = f"浏览步骤失败：{err[:220]}"
        return {
            "action": "suspend",
            "reasoning": reason,
            "resume_at": None,
            "params": {},
            "goal_progress": _goal_progress(brief, state),
            "plan_step_id": step_id,
        }

    if status == "completed":
        next_index = index + 1
        if next_index >= len(steps):
            return guard_supervisor_complete_decision(
                brief,
                state,
                {
                    "action": "complete",
                    "reasoning": "执行计划已全部完成",
                    "params": {},
                    "goal_progress": _goal_progress(brief, state),
                    "plan_step_id": "finish",
                },
            )
        plan["current_index"] = next_index
        return plan_driven_supervisor_decision(plan, brief, state, stats=stats)

    if action in CRAWL_SUPERVISOR_ACTIONS and state.get("crawl_done"):
        step["status"] = "completed"
        plan["current_index"] = _resolve_current_index(steps)
        return plan_driven_supervisor_decision(plan, brief, state, stats=stats)

    if action in CRAWL_SUPERVISOR_ACTIONS:
        target = int(brief.goals.get("target_leads") or 0)
        qualified = int(state.get("leads_qualified") or 0)
        if state.get("evaluation_done") and target > 0 and qualified >= target:
            state["crawl_done"] = True
            state["qualified_target_reached"] = True
            step["status"] = "completed"
            plan["current_index"] = _resolve_current_index(steps)
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)

    if action == "evaluate_leads" and state.get("evaluation_done"):
        if _maybe_recrawl_after_zero_qualified(brief, state, plan, stats=stats):
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)
        step["status"] = "completed"
        plan["current_index"] = _resolve_current_index(steps)
        return plan_driven_supervisor_decision(plan, brief, state, stats=stats)

    if action == "query_stats" and state.get("stats_synced"):
        if _maybe_recrawl_after_zero_qualified(brief, state, plan, stats=stats):
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)
        step["status"] = "completed"
        plan["current_index"] = _resolve_current_index(steps)
        return plan_driven_supervisor_decision(plan, brief, state, stats=stats)

    if action == "outreach":
        target = int(brief.goals.get("target_leads") or 0)
        leads = int(state.get("leads_collected") or 0)
        if target > 0 and leads >= target:
            step["status"] = "completed"
            plan["current_index"] = _resolve_current_index(steps)
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)
        if outreach_quotas_exhausted(stats or {}, brief):
            step["status"] = "completed"
            plan["current_index"] = _resolve_current_index(steps)
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)
        next_action = next_outreach_action_from_brief(stats or {}, brief)
        if not next_action:
            step["status"] = "completed"
            plan["current_index"] = _resolve_current_index(steps)
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)
        if status == "pending":
            step["status"] = "in_progress"
        platform = brief.platform or "douyin"
        reasoning = f"【计划 {step.get('order')}】{step.get('label') or 'outreach'} → {next_action}"
        decision: dict[str, Any] = {
            "action": next_action,
            "reasoning": reasoning,
            "params": dict(step.get("params") or {}),
            "goal_progress": _goal_progress(brief, state),
            "plan_step_id": step_id,
        }
        skill_id = skill_id_for_supervisor_action(next_action, platform)
        if skill_id:
            decision["skill_id"] = skill_id
        return decision

    if action in OUTREACH_LOOP_ACTIONS:
        if _maybe_recrawl_after_zero_qualified(brief, state, plan, stats=stats):
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)
        bucket = (stats or {}).get(action) if isinstance((stats or {}).get(action), dict) else {}
        if not outreach_bucket_can_do(bucket):
            step["status"] = "completed"
            plan["current_index"] = _resolve_current_index(steps)
            return plan_driven_supervisor_decision(plan, brief, state, stats=stats)

    if status == "pending":
        step["status"] = "in_progress"

    platform = brief.platform or "douyin"
    params = dict(step.get("params") or {})
    reasoning = f"【计划 {step.get('order')}】{step.get('label') or action}"
    decision: dict[str, Any] = {
        "action": action,
        "reasoning": reasoning,
        "params": params,
        "goal_progress": _goal_progress(brief, state),
        "plan_step_id": step_id,
    }
    skill_id = skill_id_for_supervisor_action(action, platform)
    if skill_id:
        decision["skill_id"] = skill_id
    if action == "complete":
        return guard_supervisor_complete_decision(brief, state, decision)
    if action == "crawl_keyword":
        revisit = build_url_revisit_decision(
            brief,
            state,
            reasoning=reasoning + "（直开已发现视频，跳过重复搜索）",
            plan_step_id=step_id,
        )
        if revisit is not None:
            return revisit
    return decision


def _goal_progress(brief: TaskBrief, state: dict[str, Any]) -> dict[str, Any]:
    target = effective_target_leads(brief, state) or int(brief.goals.get("target_leads") or 50)
    leads = effective_leads_collected(brief, state)
    qualified = effective_leads_qualified(state)
    goal_count = effective_supervisor_goal_count(brief, state)
    progress = {
        "leads_collected": leads,
        "leads_qualified": qualified,
        "goal_leads": goal_count,
        "comments_captured": int(state.get("comments_captured") or 0),
        "target_leads": target,
        "crawl_done": bool(state.get("crawl_done")),
    }
    if round_loop_enabled(brief):
        progress.update(
            {
                "repeat_mode": "round",
                "round_index": int(state.get("round_index") or 1),
                "round_leads_collected": leads,
                "round_target_leads": target,
                "total_leads_collected": int(state.get("total_leads_collected") or 0),
            }
        )
    return progress


def supervisor_goal_reached(brief: TaskBrief, state: dict[str, Any]) -> bool:
    if round_loop_enabled(brief):
        return goal_reached_for_current_round(brief, state)
    target = int(brief.goals.get("target_leads") or 0)
    if target <= 0:
        return True
    return effective_supervisor_goal_count(brief, state) >= target


def build_plan_incomplete_suspend_decision(brief: TaskBrief, state: dict[str, Any]) -> dict[str, Any]:
    target = effective_target_leads(brief, state)
    goal_count = effective_supervisor_goal_count(brief, state)
    if uses_qualified_leads_goal(brief):
        metric_label = "精准线索"
    else:
        metric_label = "线索触达"
    resume_at = None
    if is_standalone_browse_brief(brief) and standalone_can_auto_continue(brief, state):
        resume_at = _short_resume_at_iso(minutes=3)
    return {
        "action": "suspend",
        "reasoning": (
            f"战术计划步骤已跑完，但{metric_label} {goal_count}/{target} 未达标，"
            "挂起等待继续执行（非目标达成）"
        ),
        "resume_at": resume_at,
        "params": {},
        "goal_progress": _goal_progress(brief, state),
        "plan_step_id": "finish",
        "completion_outcome": "plan_incomplete",
    }


def guard_supervisor_complete_decision(
    brief: TaskBrief,
    state: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    if str(decision.get("action") or "") != "complete":
        return decision
    if supervisor_goal_reached(brief, state):
        decision = dict(decision)
        decision["completion_outcome"] = "goal_reached"
        return decision
    return build_plan_incomplete_suspend_decision(brief, state)


def _default_resume_at_iso() -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()


def _short_resume_at_iso(*, minutes: int = 3) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(minutes=max(1, int(minutes)))).isoformat()


def standalone_can_auto_continue(brief: TaskBrief, state: dict[str, Any]) -> bool:
    """Standalone 未达目标但仍有视频/搜索进度可续扫。"""
    if not is_standalone_browse_brief(brief):
        return False
    if state.get("crawl_search_exhausted"):
        return False
    target = effective_target_leads(brief, state)
    goal = effective_supervisor_goal_count(brief, state)
    if target > 0 and goal >= target:
        return False
    if int(state.get("standalone_browse_offset") or 0) > 0:
        return True
    if str(state.get("standalone_search_url") or "").strip():
        return True
    return int(state.get("videos_processed") or 0) > 0


def prepare_standalone_auto_continue(state: dict[str, Any], brief: TaskBrief) -> None:
    """重置计划到 crawl 步骤，同一次任务内自动续扫。"""
    state.pop("suspended", None)
    state.pop("resume_at", None)
    state.pop("wake_reason", None)
    state.pop("completion_outcome", None)
    state["stale_cycles"] = 0
    state.pop("crawl_done", None)
    state.pop("stats_synced", None)
    state.pop("evaluation_done", None)
    plan = state.get("execution_plan") if isinstance(state.get("execution_plan"), dict) else None
    if not isinstance(plan, dict):
        state["execution_plan"] = ensure_supervisor_execution_plan(brief, state)
        plan = state["execution_plan"]
    steps = plan.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "")
            if action == "crawl_keyword":
                step["status"] = "in_progress"
            elif action in {"query_stats", "complete"}:
                step["status"] = "pending"
        plan["current_index"] = 0
        state["execution_plan"] = plan


def format_resume_at_display(resume_at: str | None) -> str | None:
    if not resume_at:
        return None
    try:
        from zoneinfo import ZoneInfo

        dt = datetime.fromisoformat(str(resume_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return local.strftime("%Y-%m-%d %H:%M") + "（北京时间）"
    except Exception:
        text = str(resume_at).strip()
        return text[:19] if text else None


def infer_suspend_next_action(reason: str, state: dict[str, Any], brief: TaskBrief) -> str:
    reason_text = (reason or "").strip()
    reason_l = reason_text.lower()
    outcome = str(state.get("completion_outcome") or "")
    resume_next = brief.constraints.get("termination_resume_next_day", True)
    crawl_done = bool(state.get("crawl_done"))
    manual_mode = manual_acquisition_mode(brief)

    if outcome == "quota_exhausted" or "配额" in reason_text:
        if resume_next:
            return "自动恢复后：同步今日 reply/follow/dm 配额 → 从已入库评论继续独立触达"
        return "手动「继续执行」：同步配额后继续 reply / dm / follow"

    if outcome == "source_exhausted":
        if manual_mode == "account_home":
            return (
                "主页视频已扫完仍无可用评论：请加大「采集几天内评论」、放宽评估标准、"
                "提高扫描视频数或更换博主后「继续执行」"
            )
        if manual_mode == "single_video":
            return "该视频无符合时间窗的评论：请加大评论时间窗或放宽评估标准后「继续执行」"
        return "已扫完搜索列表仍无匹配：请调整线索评估标准、更换关键词或降低目标数后继续"

    if "抓取" in reason_text and any(token in reason_text for token in ("失败", "风控", "验证码")):
        return "请先确认抖音已登录且无验证码，再点击「继续执行」重新抓取"

    if any(token in reason_text for token in ("无匹配", "已入库评论", "待触达线索", "扫完")):
        if state.get("crawl_search_exhausted"):
            if manual_mode:
                return (
                    "链接内容已扫完仍无匹配线索：请加大评论时间窗、放宽评估标准或降低目标数后「继续执行」"
                )
            return "已扫完搜索列表仍无匹配：请调整线索评估标准或更换搜索词后「继续执行」"
        if resume_next:
            if manual_mode:
                return "自动恢复后会重新抓取；也可现在「继续执行」立即重试"
            return "自动恢复后会继续浏览更多视频并匹配；也可现在「继续执行」立即重试"
        if manual_mode:
            return "点击「继续执行」重新抓取并评估评论"
        return "点击「继续执行」继续浏览更多视频并匹配评论"

    if "无进展" in reason_text or "死循环" in reason_text or "连续" in reason_text:
        return "请查看 Supervisor 决策日志，调整任务配置后点击「继续执行」"

    if outcome == "plan_incomplete":
        return "点击「继续执行」从当前计划步骤继续，直至达成目标线索"

    if is_skill_flow_brief(brief) and crawl_done:
        resume_next = bool(brief.constraints.get("termination_resume_next_day", True))
        return infer_skill_flow_suspend_next_action(
            reason_text,
            state,
            brief,
            resume_next=resume_next,
            crawl_done=crawl_done,
        )

    if "crawl" in reason_l or not crawl_done:
        if manual_mode:
            return "点击「继续执行」重新抓取主页/视频评论"
        return "点击「继续执行」继续抓取关键词相关视频评论"

    return "点击「继续执行」从当前进度继续 Supervisor 循环"


def apply_suspend_state(
    state: dict[str, Any],
    brief: TaskBrief,
    reason: str,
    *,
    resume_at: str | None = None,
    completion_outcome: str | None = None,
) -> None:
    resolved_reason = (reason or "任务已挂起").strip()
    resolved_resume = (resume_at or state.get("resume_at") or _default_resume_at_iso()).strip()
    state["suspended"] = True
    state["resume_at"] = resolved_resume
    state["wake_reason"] = resolved_reason
    if completion_outcome:
        state["completion_outcome"] = completion_outcome
    elif "配额" in resolved_reason:
        state["completion_outcome"] = "quota_exhausted"
    state["next_action"] = infer_suspend_next_action(resolved_reason, state, brief)


def build_suspend_brief(
    supervisor_state: dict[str, Any],
    job_result: dict[str, Any] | None = None,
    task_brief: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not supervisor_state.get("suspended"):
        return None
    result = job_result if isinstance(job_result, dict) else {}
    brief = TaskBrief.model_validate(task_brief) if isinstance(task_brief, dict) else TaskBrief(brief_md="")
    reason = str(
        supervisor_state.get("wake_reason")
        or result.get("summary")
        or supervisor_state.get("last_crawl_error")
        or "任务已挂起"
    ).strip()
    resume_at = str(supervisor_state.get("resume_at") or "").strip() or None
    next_action = str(supervisor_state.get("next_action") or "").strip()
    if not next_action:
        next_action = infer_suspend_next_action(reason, supervisor_state, brief)
    resume_display = format_resume_at_display(resume_at)
    manual_resume = "您也可随时点击「继续执行」跳过等待，立即恢复运行"
    brief = {
        "reason": reason,
        "resume_at": resume_at,
        "resume_at_display": resume_display,
        "next_action": next_action,
        "manual_resume": manual_resume,
    }
    try:
        from app.services.page_diagnosis.reporter import merge_diagnosis_into_suspend_brief

        brief = merge_diagnosis_into_suspend_brief(brief, supervisor_state)
    except Exception:
        pass
    return brief


def build_execution_note(
    *,
    job_status: str,
    job_stage: str,
    job_result: dict[str, Any] | None = None,
) -> str | None:
    result = job_result if isinstance(job_result, dict) else {}
    outcome = str(result.get("completion_outcome") or "")
    supervisor_state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
    progress = result.get("data_snapshot", {}).get("progress") if isinstance(result.get("data_snapshot"), dict) else {}
    if not isinstance(progress, dict):
        progress = {}
    leads = int(progress.get("leads_collected") or supervisor_state.get("leads_collected") or 0)
    target = int(progress.get("target_leads") or 0)
    progress_text = f"{leads}/{target}" if target else str(leads)

    if job_status == "running" and job_stage in {"observe", "plan", "act", "track"}:
        return f"Supervisor 正在执行「{job_stage}」阶段…"
    if job_status == "completed":
        if outcome == "goal_reached":
            return f"Supervisor 已结束：目标线索已达成（{progress_text}）。"
        return f"Supervisor 已结束（{progress_text}）。"
    if job_status == "suspended" or (job_status == "pending" and supervisor_state.get("suspended")):
        if outcome == "source_exhausted":
            task_brief_raw = None
            orch = result.get("orchestration")
            if isinstance(orch, dict):
                task_brief_raw = orch.get("task_brief")
            brief_for_note = (
                TaskBrief.model_validate(task_brief_raw)
                if isinstance(task_brief_raw, dict)
                else TaskBrief(brief_md="")
            )
            if manual_acquisition_mode(brief_for_note):
                return (
                    f"Supervisor 已挂起：内容已扫完且未达成目标（{progress_text}），"
                    "请加大评论时间窗、放宽评估标准或更换链接后继续。"
                )
            return f"Supervisor 已挂起：搜索源已耗尽且未达成目标（{progress_text}），请调整关键词或匹配条件。"
        task_brief = None
        orch = result.get("orchestration")
        if isinstance(orch, dict):
            task_brief = orch.get("task_brief")
        suspend = build_suspend_brief(supervisor_state, result, task_brief if isinstance(task_brief, dict) else None)
        if suspend:
            parts = [f"已暂停：{suspend['reason']}"]
            if suspend.get("resume_at_display"):
                parts.append(f"自动恢复：{suspend['resume_at_display']}")
            parts.append(f"下一步：{suspend['next_action']}")
            return " · ".join(parts)
        if outcome == "plan_incomplete":
            return f"Supervisor 已挂起：计划步骤跑完但未达成目标（{progress_text}），请继续执行。"
        if outcome == "quota_exhausted":
            return f"Supervisor 已挂起：今日触达配额已用尽（{progress_text}），待配额重置后继续。"
        wake = str(supervisor_state.get("wake_reason") or result.get("summary") or "").strip()
        if wake:
            return f"Supervisor 已挂起：{wake}"
        return "Supervisor 已挂起，等待下次继续执行。"
    if job_status in {"failed", "dead_letter"}:
        return "Supervisor 执行失败，请查看决策日志。"
    return None


def bootstrap_only_plan_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Bootstrap 已完成搜索/进 Feed/开侧栏后的精简计划（Agent 不得再加搜索步骤）。"""
    keyword = str(params.get("keyword") or "关键词").strip()
    limit = int(params.get("crawl_video_limit") or params.get("content_limit") or params.get("video_limit") or 1)
    return [
        {
            "id": "understand",
            "order": 1,
            "title": "确认当前在 Feed 评论侧栏",
            "success_criteria": "browser_get_page_info scene=feed_with_comments，侧栏可见「全部评论」",
            "status": "completed",
            "notes": "bootstrap 自动引导已完成",
        },
        {
            "id": "browse_outreach",
            "order": 2,
            "title": f"浏览评论并在 UI 直接触达（最多 {limit} 个视频）",
            "success_criteria": (
                f"关键词「{keyword}」相关评论；仅 target=comment_sidebar 滚动；"
                "匹配即回复/私信/关注；禁止重复搜索或整页乱滑"
            ),
            "status": "pending",
        },
        {
            "id": "deliver",
            "order": 3,
            "title": "结构化交付",
            "success_criteria": "task_complete 含 outreach 与 comments_by_video，禁止编造",
            "status": "pending",
        },
    ]
