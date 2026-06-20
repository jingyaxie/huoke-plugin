from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.skill import SkillOut
from app.services.agent_browser_session import AgentBrowserSession, AgentSessionManager
from app.services.agent_llm import resolve_default_provider
from app.services.ai_client import AIClientFactory
from app.services.playwright_tools import PlaywrightToolExecutor
from app.services.skill_executor import SkillExecutor
from app.services.skill_store import SkillStore, resolve_skill_id
from app.services.skill_runner_service import SkillRunnerService
from app.services.outreach_policy import random_interval_sec
from app.services.task_brief_service import TaskBrief, is_skill_flow_brief
from app.services.standalone_browse_adapter import is_standalone_browse_brief
from app.services.task_context_service import build_data_snapshot
from app.services.task_round_service import (
    complete_current_round,
    effective_leads_collected,
    effective_leads_qualified,
    effective_supervisor_goal_count,
    effective_target_leads,
    ensure_round_state,
    goal_reached_for_current_round,
    max_rounds_from_brief,
    round_loop_enabled,
    start_next_round,
    standalone_outreach_incomplete,
    uses_qualified_leads_goal,
)
from app.services.task_job_ledger_service import append_memory_ledger_action, build_task_ledger
from app.services.task_sandbox_runtime import TaskSandboxRuntime
from app.services.task_skill_playbook import (
    ACTION_TO_SKILL,
    allowed_supervisor_actions,
    skill_id_from_brief,
)
from app.services.supervisor_outreach import (
    max_run_days_from_brief,
    outreach_interval_from_brief,
    outreach_quotas_exhausted,
    outreach_stats_ready,
    merge_job_persisted_comment_ids,
    persist_crawl_skill_result,
    resolve_outreach_action_with_policy_async,
    run_evaluate_leads_phase,
    validate_crawl_skill_result,
    crawl_search_phase_succeeded,
)
from app.services.supervisor_action_guard import guard_supervisor_action, requires_lead_evaluation
from app.services.supervisor_crawl_helpers import (
    OUTREACH_LOOP_ACTIONS,
    apply_crawl_video_limit_aliases,
    browser_headless,
    build_crawl_action_params,
    build_crawl_day_params,
    build_crawl_keyword_params,
    crawl_evaluate_gate,
    CRAWL_SUPERVISOR_ACTIONS,
    count_crawl_from_skill_result,
    effective_crawl_video_limit,
    merge_skill_flow_crawl_params,
    merge_outreach_params,
    prepare_crawl_retry,
    prepare_plan_recrawl,
    record_crawl_round_without_evaluation,
    reset_crawl_evaluate_gate_state,
    should_resume_crawl_on_no_match,
    show_browser,
    maybe_prefer_url_revisit_decision,
    mark_url_revisited,
)
from app.services.task_execution_plan import (
    advance_supervisor_plan,
    apply_suspend_state,
    build_plan_incomplete_suspend_decision,
    build_supervisor_execution_plan,
    ensure_supervisor_execution_plan,
    guard_supervisor_complete_decision,
    plan_driven_supervisor_decision,
    prepare_standalone_auto_continue,
    standalone_can_auto_continue,
    sync_supervisor_plan_from_state,
)

MAX_SUPERVISOR_CYCLES = 15
MIN_CYCLE_INTERVAL_SEC = 2.0
STALE_CYCLE_LIMIT = 3
REPEAT_ACTION_LIMIT = 3
PROGRESS_ACTIONS = frozenset({"crawl_keyword", "crawl_content_url", "crawl_profile", "reply", "dm", "follow"})
CRAWL_ACTION_TIMEOUT_SEC = 600
OUTREACH_ACTION_TIMEOUT_SEC = 180

SUPERVISOR_ACTIONS = [
    "crawl_keyword",
    "crawl_content_url",
    "crawl_profile",
    "evaluate_leads",
    "query_stats",
    "query_comments",
    "reply",
    "dm",
    "follow",
    "check_login",
    "suspend",
    "complete",
    "fail",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_resume_at() -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()



def _progress_fingerprint(state: dict[str, Any]) -> str:
    return "|".join(
        [
            str(int(state.get("leads_collected") or 0)),
            str(int(state.get("comments_captured") or 0)),
            str(bool(state.get("crawl_done"))),
            str(bool(state.get("stats_synced"))),
            str(state.get("last_action") or ""),
        ]
    )


def _add_leads_to_state(brief: TaskBrief, state: dict[str, Any], count: int) -> None:
    if count <= 0:
        return
    state["leads_collected"] = int(state.get("leads_collected") or 0) + count
    if round_loop_enabled(brief):
        ensure_round_state(brief, state)
        state["round_leads_collected"] = int(state.get("round_leads_collected") or 0) + count


def _parse_brief(raw: dict[str, Any] | None) -> TaskBrief:
    if not isinstance(raw, dict):
        return TaskBrief(brief_md="未生成任务简报")
    return TaskBrief.model_validate(raw)


def _extract_outreach_leads(skill_result: dict[str, Any]) -> int:
    """从 ui_flow / ui_first 内联触达结果提取条数。"""
    for key in ("inline_outreach", "outreach"):
        inline = skill_result.get(key)
        if isinstance(inline, dict):
            total = (
                int(inline.get("replies") or 0)
                + int(inline.get("follows") or 0)
                + int(inline.get("dms") or 0)
                + int(inline.get("validated") or 0)
            )
            if total > 0:
                return total
    inner = skill_result.get("result") if isinstance(skill_result.get("result"), dict) else skill_result
    if not isinstance(inner, dict):
        return 0
    outreach = inner.get("outreach")
    if isinstance(outreach, dict):
        for key in ("replies", "reply_count", "leads", "total"):
            val = outreach.get(key)
            if val is not None:
                return int(val)
        details = outreach.get("reply_details") or outreach.get("details") or []
        if isinstance(details, list):
            return len(details)
    return int(inner.get("outreach_replies") or inner.get("replies_sent") or 0)


def _extract_crawl_captured_count(skill_result: dict[str, Any]) -> int:
    return count_crawl_from_skill_result(skill_result)



def _supervisor_browser_headless(brief: TaskBrief) -> bool:
    if is_skill_flow_brief(brief):
        return browser_headless(brief)
    return True


class TaskSupervisorService:
    """混合架构 Supervisor：读简报 + 数据快照 → LLM 战术决策 → 确定性 Skill 执行。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        platform: str,
        account_id: str,
        *,
        db_session: Session | None = None,
        provider: str = "deepseek",
        agent_profile_id: str = "",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.account_id = account_id
        self.db_session = db_session
        self.provider = provider
        self.agent_profile_id = (agent_profile_id or "").strip()
        self._skill_store = SkillStore(settings)
        self._sandbox_runtime: TaskSandboxRuntime | None = None

    async def run(
        self,
        *,
        brief: TaskBrief,
        job_result: dict[str, Any],
        job_id: str = "",
        timeout_seconds: int = 600,
        dry_run: bool = False,
        on_progress: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        result = dict(job_result)
        state = result.get("supervisor_state")
        if not isinstance(state, dict):
            state = {}
        if job_id:
            prior_job = str(state.get("job_id") or "").strip()
            if prior_job and prior_job != job_id:
                state.pop("watched_content_ids", None)
                state.pop("crawl_search_exhausted", None)
            state["job_id"] = job_id
        ensure_round_state(brief, state)
        cycles = result.get("supervisor_cycles")
        if not isinstance(cycles, list):
            cycles = []

        self._sandbox_runtime = TaskSandboxRuntime(self.settings, self.tenant_id, job_id) if job_id else None
        if self._sandbox_runtime and self._sandbox_runtime.available:
            self._sandbox_runtime.load_helpers()
            self._sandbox_runtime.sync_supervisor_state(state)
        if bool(brief.goals.get("force_refresh")):
            state.pop("crawl_done", None)
            state.pop("comments_captured", None)
            state.pop("stats_synced", None)
            state.pop("last_stats", None)
            state.pop("outreach_validated", None)
            state.pop("last_validate_action", None)

        if not isinstance(state.get("execution_plan"), dict):
            state["execution_plan"] = ensure_supervisor_execution_plan(brief, state)
        else:
            state["execution_plan"] = ensure_supervisor_execution_plan(brief, state)

        self._maybe_wake_suspended_state(state, brief)
        max_days = max_run_days_from_brief(brief)
        day_index = int(state.get("day_index") or 1)
        if max_days > 0 and day_index > max_days:
            return {
                **result,
                "supervisor_state": state,
                "supervisor_cycles": cycles[-60:],
                "dry_run": dry_run,
                "status": "completed",
                "summary": f"已达 max_run_days={max_days}，停止执行（线索 {state.get('leads_collected', 0)}/{brief.goals.get('target_leads')}）",
                "error": "",
                "completion_outcome": "max_run_days_reached",
            }

        deadline = asyncio.get_running_loop().time() + max(60.0, float(timeout_seconds))
        session: AgentBrowserSession | None = None
        browser_headless = _supervisor_browser_headless(brief)
        if not dry_run:
            session = await AgentSessionManager.get_instance().create_stable(
                self.tenant_id,
                self.platform,
                self.settings,
                account_id=self.account_id,
                headless=browser_headless,
                owner_job_id=job_id or None,
            )
            result["browser_session_id"] = session.session_id

        final_status = "completed"
        final_summary = ""
        final_error = ""

        try:
            for cycle_idx in range(MAX_SUPERVISOR_CYCLES):
                if asyncio.get_running_loop().time() >= deadline:
                    final_status = "failed"
                    final_error = "Supervisor 执行超时"
                    break

                stale_cycles = int(state.get("stale_cycles") or 0)
                if stale_cycles >= STALE_CYCLE_LIMIT:
                    decision = self._make_suspend_decision(
                        state,
                        brief,
                        f"连续 {stale_cycles} 轮无进展，强制挂起避免死循环",
                    )
                    action = "suspend"
                    reasoning = str(decision.get("reasoning") or "")
                    cycles.append(self._cycle_record(cycle_idx + 1, decision, {"status": "suspended"}))
                    self._mark_suspended(state, brief, reasoning, resume_at=str(decision.get("resume_at") or ""))
                    final_status = "suspended"
                    final_summary = reasoning
                    break

                snapshot = build_data_snapshot(
                    brief=brief,
                    job_result=result,
                    settings=self.settings,
                    tenant_id=self.tenant_id,
                    platform=self.platform,
                    account_id=self.account_id,
                    db_session=self.db_session,
                    job_id=job_id,
                )
                execution_plan = state.get("execution_plan")
                if isinstance(execution_plan, dict):
                    execution_plan = sync_supervisor_plan_from_state(execution_plan, state)
                    state["execution_plan"] = execution_plan
                    snapshot["execution_plan"] = execution_plan
                decision = await self._decide(brief, snapshot, state)
                action = str(decision.get("action") or "fail")
                reasoning = str(decision.get("reasoning") or "")

                if action in CRAWL_SUPERVISOR_ACTIONS and state.get("crawl_done"):
                    decision = await self._heuristic_decide(brief, snapshot, state)
                    action = str(decision.get("action") or "fail")
                    reasoning = str(decision.get("reasoning") or reasoning)

                if action == "reply":
                    decision = await self._resolve_outreach_decision(
                        decision,
                        brief,
                        state,
                        action="reply",
                        snapshot_stats=snapshot.get("interaction_stats")
                        if isinstance(snapshot.get("interaction_stats"), dict)
                        else None,
                    )
                    action = str(decision.get("action") or "fail")
                    reasoning = str(decision.get("reasoning") or reasoning)
                elif action in {"dm", "follow"}:
                    decision = await self._resolve_outreach_decision(
                        decision,
                        brief,
                        state,
                        action=action,
                        snapshot_stats=snapshot.get("interaction_stats")
                        if isinstance(snapshot.get("interaction_stats"), dict)
                        else None,
                    )
                    action = str(decision.get("action") or "fail")
                    reasoning = str(decision.get("reasoning") or reasoning)

                if action == "query_stats" and state.get("last_action") == "query_stats":
                    decision = await self._heuristic_decide(brief, snapshot, state)
                    action = str(decision.get("action") or "fail")
                    reasoning = str(decision.get("reasoning") or reasoning)

                repeat_action = str(state.get("_repeat_action") or "")
                repeat_count = int(state.get("_repeat_action_count") or 0)
                if (
                    action == repeat_action
                    and action in PROGRESS_ACTIONS
                    and repeat_count >= REPEAT_ACTION_LIMIT
                ):
                    decision = self._make_suspend_decision(
                        state,
                        brief,
                        f"动作 {action} 连续重复 {repeat_count} 次无进展，强制挂起",
                    )
                    action = "suspend"
                    reasoning = str(decision.get("reasoning") or "")

                if (
                    action in CRAWL_SUPERVISOR_ACTIONS
                    and not state.get("crawl_done")
                    and self._crawl_failure_should_suspend(brief, state)
                ):
                    reason = str(state.get("last_crawl_error") or "").strip()
                    if not reason:
                        reason = "抓取已失败，挂起避免重复搜索触发风控"
                    decision = self._make_suspend_decision(
                        state,
                        brief,
                        reason,
                    )
                    action = "suspend"
                    reasoning = str(decision.get("reasoning") or "")

                guard_stats = snapshot.get("interaction_stats")
                if not isinstance(guard_stats, dict):
                    guard_stats = state.get("last_stats") if isinstance(state.get("last_stats"), dict) else None
                guarded = guard_supervisor_action(
                    decision,
                    brief=brief,
                    state=state,
                    stats=guard_stats,
                )
                if guarded is not decision:
                    decision = guarded
                    action = str(decision.get("action") or "fail")
                    reasoning = str(decision.get("reasoning") or reasoning)

                plan_step_id = decision.get("plan_step_id")
                await self._emit(on_progress, "supervisor_decide", {
                    "cycle": cycle_idx + 1,
                    "action": action,
                    "reasoning": reasoning,
                    "plan_step_id": plan_step_id,
                    "execution_plan": state.get("execution_plan"),
                    "snapshot": snapshot,
                })

                if action == "complete":
                    decision = guard_supervisor_complete_decision(brief, state, decision)
                    action = str(decision.get("action") or "complete")
                    reasoning = str(decision.get("reasoning") or reasoning)
                    outcome = decision.get("completion_outcome")
                    if isinstance(outcome, str) and outcome:
                        state["completion_outcome"] = outcome
                    if action == "suspend":
                        resume_at = str(decision.get("resume_at") or state.get("resume_at") or "")
                        if not resume_at:
                            resume_at = _default_resume_at()
                            decision["resume_at"] = resume_at
                        wake_reason = reasoning or "未达成目标，挂起等待继续执行"
                        if await self._try_standalone_auto_continue(
                            brief=brief,
                            state=state,
                            reasoning=wake_reason,
                            on_progress=on_progress,
                        ):
                            cycles.append(
                                self._cycle_record(
                                    cycle_idx + 1,
                                    {**decision, "action": "auto_continue", "reasoning": wake_reason},
                                    {"status": "auto_continue", "summary": wake_reason},
                                )
                            )
                            continue
                        self._mark_suspended(
                            state,
                            brief,
                            wake_reason,
                            resume_at=resume_at,
                            completion_outcome=str(outcome) if isinstance(outcome, str) else None,
                        )
                        cycles.append(self._cycle_record(cycle_idx + 1, decision, {"status": "suspended", "summary": wake_reason}))
                        final_status = "suspended"
                        final_summary = wake_reason
                        break
                    final_status = "completed"
                    final_summary = reasoning or "目标已达成"
                    cycles.append(self._cycle_record(cycle_idx + 1, decision, {"status": "completed"}))
                    break
                if action == "fail":
                    final_status = "failed"
                    final_error = reasoning or "Supervisor 判定失败"
                    cycles.append(self._cycle_record(cycle_idx + 1, decision, {"status": "failed"}))
                    break
                if action == "suspend":
                    resume_at = str(decision.get("resume_at") or state.get("resume_at") or "")
                    if not resume_at:
                        resume_at = _default_resume_at()
                        decision["resume_at"] = resume_at
                    wake_reason = reasoning or "今日配额已用尽，按策略挂起等待下次唤醒"
                    outcome = decision.get("completion_outcome")
                    completion = str(outcome) if isinstance(outcome, str) else None
                    if not completion and "配额" in wake_reason:
                        completion = "quota_exhausted"
                    if (
                        completion == "plan_incomplete"
                        and await self._try_standalone_auto_continue(
                            brief=brief,
                            state=state,
                            reasoning=wake_reason,
                            on_progress=on_progress,
                        )
                    ):
                        cycles.append(
                            self._cycle_record(
                                cycle_idx + 1,
                                {**decision, "action": "auto_continue", "reasoning": wake_reason},
                                {"status": "auto_continue", "summary": wake_reason},
                            )
                        )
                        continue
                    self._mark_suspended(
                        state,
                        brief,
                        wake_reason,
                        resume_at=resume_at,
                        completion_outcome=completion,
                    )
                    state["day_index"] = int(state.get("day_index") or 1)
                    cycles.append(self._cycle_record(cycle_idx + 1, decision, {"status": "suspended", "summary": wake_reason}))
                    final_status = "suspended"
                    final_summary = wake_reason
                    break

                await self._emit(on_progress, "supervisor_act_start", {
                    "cycle": cycle_idx + 1,
                    "action": action,
                    "summary": f"正在执行 {action}…",
                })

                action_params = decision.get("params") if isinstance(decision.get("params"), dict) else {}
                if action_params.get("_revisit_under_crawl_step"):
                    state["_revisit_under_crawl_step"] = True
                    revisit_id = str(action_params.get("_revisit_content_id") or "").strip()
                    if revisit_id:
                        state["_revisit_content_id"] = revisit_id

                skill_result = await self._execute_action(
                    action=action,
                    params=action_params,
                    session=session,
                    brief=brief,
                    dry_run=dry_run,
                    state=state,
                    job_id=job_id,
                    on_progress=on_progress,
                )
                cycles.append(self._cycle_record(cycle_idx + 1, decision, skill_result))
                fp_before = _progress_fingerprint(state)
                self._update_state(
                    state,
                    action,
                    skill_result,
                    brief,
                    dry_run=dry_run,
                    params=decision.get("params") if isinstance(decision.get("params"), dict) else {},
                )
                fp_after = _progress_fingerprint(state)
                self._track_loop_guards(state, action=action, fp_before=fp_before, fp_after=fp_after)
                ok = not skill_result.get("error") and str(skill_result.get("status", "")).lower() != "failed"

                result["supervisor_state"] = state
                result["supervisor_cycles"] = cycles[-60:]
                result["data_snapshot"] = snapshot
                result["task_ledger"] = build_task_ledger(
                    job_id=job_id,
                    settings=self.settings,
                    tenant_id=self.tenant_id,
                    platform=self.platform,
                    account_id=self.account_id,
                    db_session=self.db_session,
                    memory_ledger=state.get("task_ledger") if dry_run else None,
                )
                if self._sandbox_runtime and self._sandbox_runtime.available:
                    result["sandbox_stats"] = self._sandbox_runtime.get_summary()

                await self._emit(on_progress, "supervisor_act", {
                    "cycle": cycle_idx + 1,
                    "action": action,
                    "ok": not skill_result.get("error"),
                    "summary": skill_result.get("summary") or skill_result.get("message") or "",
                })

                goal_progress = decision.get("goal_progress")
                if isinstance(goal_progress, dict):
                    if round_loop_enabled(brief):
                        ensure_round_state(brief, state)
                        lead_value = goal_progress.get(
                            "round_leads_collected",
                            goal_progress.get("leads_collected", state.get("round_leads_collected")),
                        )
                        lead_value = max(int(lead_value or 0), int(state.get("round_leads_collected") or 0))
                        state["round_leads_collected"] = lead_value
                        state["leads_collected"] = lead_value
                    else:
                        lead_value = goal_progress.get("leads_collected", state.get("leads_collected"))
                        state["leads_collected"] = max(int(lead_value or 0), int(state.get("leads_collected") or 0))

                if self._goal_reached(brief, state):
                    if round_loop_enabled(brief):
                        finished_round = complete_current_round(brief, state)
                        if start_next_round(brief, state):
                            state["execution_plan"] = ensure_supervisor_execution_plan(brief, state)
                            final_status = "pending"
                            final_summary = (
                                f"第 {finished_round['round']} 轮已达成 "
                                f"{finished_round['leads_collected']}/{finished_round['target_leads']}，"
                                f"已开启第 {state.get('round_index')} 轮"
                            )
                            continue
                        final_status = "completed"
                        final_summary = (
                            f"循环任务已完成 {max_rounds_from_brief(brief)} 轮，"
                            f"累计线索 {state.get('total_leads_collected', 0)}"
                        )
                        state["completion_outcome"] = "max_rounds_reached"
                        break
                    final_status = "completed"
                    final_summary = f"已达成目标线索 {state.get('leads_collected', 0)}"
                    break

                if action in {"reply", "dm", "follow"} and ok:
                    lo, hi = outreach_interval_from_brief(brief)
                    await asyncio.sleep(random_interval_sec(lo, hi))

                if (
                    action in CRAWL_SUPERVISOR_ACTIONS
                    and not state.get("crawl_done")
                    and self._crawl_failure_should_suspend(brief, state)
                ):
                    await self._maybe_run_page_diagnosis(
                        state=state,
                        brief=brief,
                        action=action,
                        skill_result=skill_result,
                        session=session,
                        dry_run=dry_run,
                    )
                    reason = str(state.get("last_crawl_error") or "").strip()
                    if not reason:
                        reason = "抓取失败，挂起避免重复搜索触发风控"
                    if state.get("crawl_risk_blocked"):
                        reason = "抖音验证码/风控拦截，请手动完成验证后重试"
                    suspend_decision = self._make_suspend_decision(state, brief, reason)
                    self._mark_suspended(
                        state,
                        brief,
                        reason,
                        resume_at=str(suspend_decision.get("resume_at") or ""),
                    )
                    cycles.append(self._cycle_record(cycle_idx + 1, suspend_decision, {"status": "suspended"}))
                    final_status = "suspended"
                    final_summary = str(state.get("wake_reason") or reason)
                    break

                await asyncio.sleep(MIN_CYCLE_INTERVAL_SEC)
            else:
                if final_status != "failed":
                    suspend_decision = self._make_suspend_decision(
                        state,
                        brief,
                        f"单轮已达上限 {MAX_SUPERVISOR_CYCLES} 次循环，挂起等待下次唤醒",
                    )
                    wake = str(suspend_decision.get("reasoning") or "")
                    self._mark_suspended(
                        state,
                        brief,
                        wake,
                        resume_at=str(suspend_decision.get("resume_at") or ""),
                    )
                    cycles.append(self._cycle_record(len(cycles) + 1, suspend_decision, {"status": "suspended"}))
                    final_status = "suspended"
                    final_summary = wake

        finally:
            if session is not None and not getattr(session, "stable_mode", False):
                await session.close()
            self._sandbox_runtime = None

        final_snapshot = build_data_snapshot(
            brief=brief,
            job_result={**result, "supervisor_state": state, "supervisor_cycles": cycles[-60:]},
            settings=self.settings,
            tenant_id=self.tenant_id,
            platform=self.platform,
            account_id=self.account_id,
            db_session=self.db_session,
            job_id=job_id,
        )
        result["data_snapshot"] = final_snapshot
        result["execution_stats"] = final_snapshot.get("execution_stats")
        result["task_ledger"] = final_snapshot.get("task_ledger")
        result["completion_outcome"] = state.get("completion_outcome")

        return {
            **result,
            "supervisor_state": state,
            "supervisor_cycles": cycles[-60:],
            "dry_run": dry_run,
            "status": final_status,
            "summary": final_summary or final_error,
            "error": final_error,
        }

    async def _decide(
        self,
        brief: TaskBrief,
        snapshot: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        execution_plan = state.get("execution_plan")
        if isinstance(execution_plan, dict):
            stats = snapshot.get("interaction_stats") if isinstance(snapshot.get("interaction_stats"), dict) else {}
            planned = plan_driven_supervisor_decision(
                execution_plan,
                brief,
                state,
                stats=stats,
            )
            if planned is not None and str(planned.get("action") or "") not in {"", "fail"}:
                return await self._normalize_decision(planned, brief, snapshot, state)

        if self._supervisor_plan_only(brief):
            return await self._heuristic_decide(brief, snapshot, state)

        client, model = self._resolve_llm()
        if client is None or not model:
            return await self._heuristic_decide(brief, snapshot, state)

        allowed = brief.allowed_skills or []
        skill_lines = [
            f"- {row.get('supervisor_action')} → skill `{row.get('skill_id')}`"
            f"（{row.get('purpose')}）"
            for row in allowed
            if isinstance(row, dict)
        ]
        skill_block = "\n".join(skill_lines) if skill_lines else "\n".join(
            f"- {act} → `{sid}`" for act, sid in ACTION_TO_SKILL.items()
        )

        system = (
            "你是获客任务 Supervisor。阅读任务简报与数据快照，输出下一战术动作。"
            "只输出 JSON：action, reasoning, params(object), goal_progress(object)。"
            f"action 仅允许：{', '.join(allowed_supervisor_actions())}。"
            "【Skill 白名单 — action 必须对应以下 Skill，禁止臆造其他 Skill】\n"
            f"{skill_block}\n"
            "战术原则：未抓取时 crawl_keyword；crawl_done=true 后禁止再次 crawl_keyword；"
            "触达前 query_stats；reply 的 comment_id 由系统从库中选定，禁止臆造；"
            "触达仅 reply/dm/follow 三选一；配额用尽 suspend；目标达成 complete。"
            "params 须满足对应 Skill 必填参数。"
        )
        user = json.dumps(
            {
                "task_brief_md": brief.brief_md,
                "allowed_skills": allowed,
                "goals": brief.goals,
                "constraints": brief.constraints,
                "success_criteria": brief.success_criteria,
                "data_snapshot": snapshot,
                "supervisor_state": state,
                "sandbox_stats": snapshot.get("sandbox_stats"),
            },
            ensure_ascii=False,
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("action") in allowed_supervisor_actions():
                return await self._normalize_decision(data, brief, snapshot, state)
        except Exception:
            pass
        return await self._heuristic_decide(brief, snapshot, state)

    @staticmethod
    def _supervisor_plan_only(brief: TaskBrief) -> bool:
        if bool(brief.goals.get("supervisor_plan_only")):
            return True
        return is_skill_flow_brief(brief)

    async def _normalize_decision(
        self,
        decision: dict[str, Any],
        brief: TaskBrief,
        snapshot: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """校验 action 在白名单内，非法动作回退启发式。"""
        decision = guard_supervisor_action(
            decision,
            brief=brief,
            state=state,
            stats=snapshot.get("interaction_stats") if isinstance(snapshot.get("interaction_stats"), dict) else None,
        )
        action = str(decision.get("action") or "")
        if action in CRAWL_SUPERVISOR_ACTIONS and state.get("crawl_done"):
            return await self._heuristic_decide(brief, snapshot, state)
        if action in {"reply", "dm", "follow"}:
            return await self._resolve_outreach_decision(
                decision,
                brief,
                state,
                action=action,
                snapshot_stats=snapshot.get("interaction_stats")
                if isinstance(snapshot.get("interaction_stats"), dict)
                else None,
            )
        if action in {"suspend", "complete", "fail"}:
            return decision
        if action == "evaluate_leads":
            return decision
        skill_id = skill_id_from_brief(brief, action)
        if not skill_id:
            return await self._heuristic_decide(brief, snapshot, state)
        allowed_ids = {
            str(row.get("skill_id") or "")
            for row in (brief.allowed_skills or [])
            if isinstance(row, dict)
        }
        crawl_skill = skill_id_from_brief(brief, "crawl_keyword")
        if allowed_ids and skill_id not in allowed_ids:
            if action in CRAWL_SUPERVISOR_ACTIONS and crawl_skill in allowed_ids:
                decision["skill_id"] = crawl_skill
                return decision
            if action == "evaluate_leads":
                return decision
            return await self._heuristic_decide(brief, snapshot, state)
        decision["skill_id"] = skill_id
        return decision

    def _should_resume_crawl_on_no_match(
        self,
        brief: TaskBrief,
        state: dict[str, Any],
        stats: dict[str, Any] | None = None,
    ) -> bool:
        if not is_skill_flow_brief(brief):
            return False
        return should_resume_crawl_on_no_match(brief, state, stats)

    def _prepare_crawl_retry(self, state: dict[str, Any]) -> None:
        prepare_crawl_retry(state)

    def _crawl_keyword_decision(
        self,
        brief: TaskBrief,
        state: dict[str, Any],
        reasoning: str,
    ) -> dict[str, Any]:
        leads = int(state.get("leads_collected") or 0)
        target = int(brief.goals.get("target_leads") or 50)
        return maybe_prefer_url_revisit_decision(
            brief,
            state,
            {
                "action": "crawl_keyword",
                "skill_id": skill_id_from_brief(brief, "crawl_keyword"),
                "reasoning": reasoning,
                "params": build_crawl_keyword_params(brief),
                "goal_progress": {
                    "leads_collected": leads,
                    "comments_captured": int(state.get("comments_captured") or 0),
                    "target_leads": target,
                },
            },
        )

    def _should_resume_crawl_on_quota_exhausted(
        self,
        brief: TaskBrief,
        state: dict[str, Any],
    ) -> bool:
        return False

    def _quota_exhausted_decision(
        self,
        brief: TaskBrief,
        state: dict[str, Any],
        stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._should_resume_crawl_on_quota_exhausted(brief, state):
            self._prepare_crawl_retry(state)
            state["outreach_quota_exhausted"] = True
            return self._crawl_keyword_decision(
                brief,
                state,
                "今日触达配额已用尽，继续浏览搜索列表并入库匹配评论（暂不触达）",
            )
        day_index = int(state.get("day_index") or 1)
        leads = int(state.get("leads_collected") or 0)
        target = int(brief.goals.get("target_leads") or 50)
        resume_at = _default_resume_at()
        exhausted = state.get("crawl_search_exhausted")
        reason = "今日触达配额已用尽"
        if exhausted:
            reason = (
                f"今日触达配额已用尽，且已扫完搜索列表（{leads}/{target} 条线索）；"
                f"待配额重置后继续"
            )
        return {
            "action": "suspend",
            "reasoning": reason,
            "resume_at": resume_at,
            "params": {},
            "goal_progress": {"leads_collected": leads, "target_leads": target},
            "completion_outcome": "quota_exhausted",
        }

    def _no_match_decision(
        self,
        brief: TaskBrief,
        state: dict[str, Any],
        note: str,
        stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if note == "今日触达配额已用尽":
            return self._quota_exhausted_decision(brief, state, stats)
        if self._should_resume_crawl_on_no_match(brief, state, stats):
            self._prepare_crawl_retry(state)
            return self._crawl_keyword_decision(
                brief,
                state,
                note or "当前批次无匹配评论，继续浏览搜索列表中的更多视频",
            )
        exhausted_note = note or "已扫完当前搜索列表仍无匹配评论"
        completion_outcome = None
        if state.get("crawl_search_exhausted"):
            completion_outcome = "source_exhausted"
            crawl_err = str(state.get("last_crawl_error") or "").strip()
            exhausted_note = crawl_err or "已扫完当前搜索列表，LLM 评估后仍无待触达线索"
        return self._make_suspend_decision(
            state,
            brief,
            exhausted_note,
            completion_outcome=completion_outcome,
        )

    async def _resolve_outreach_decision(
        self,
        decision: dict[str, Any],
        brief: TaskBrief,
        state: dict[str, Any],
        *,
        action: str,
        snapshot_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """触达参数强制从已入库评论选取，禁止臆造 comment_id / user_id。"""
        if self.db_session is None:
            return self._make_suspend_decision(
                state,
                brief,
                "触达需要数据库会话，无法从已入库评论选线索",
            )
        stats = state.get("last_stats") if isinstance(state.get("last_stats"), dict) else {}
        if not outreach_stats_ready(stats, brief) and isinstance(snapshot_stats, dict):
            stats = snapshot_stats
        resolved_action, target_params, note = await resolve_outreach_action_with_policy_async(
            stats,
            brief,
            db_session=self.db_session,
            settings=self.settings,
            tenant_id=self.tenant_id,
            platform=brief.platform or self.platform,
            account_id=self.account_id,
            state=state,
            provider=self.provider,
        )
        use_action = resolved_action or action
        if not target_params:
            return self._no_match_decision(brief, state, note, stats)
        leads = int(state.get("leads_collected") or 0)
        target = int(brief.goals.get("target_leads") or 50)
        return {
            **decision,
            "action": use_action,
            "skill_id": skill_id_from_brief(brief, use_action),
            "reasoning": note or f"已从库中选定待{use_action}目标",
            "params": target_params,
            "goal_progress": {
                "leads_collected": leads,
                "comments_captured": int(state.get("comments_captured") or 0),
                "target_leads": target,
            },
        }

    @staticmethod
    def _crawl_failure_should_suspend(brief: TaskBrief, state: dict[str, Any]) -> bool:
        if int(state.get("crawl_failures") or 0) < 1:
            return False
        return bool(state.get("crawl_risk_blocked")) if is_skill_flow_brief(brief) else True

    def _maybe_wake_suspended_state(self, state: dict[str, Any], brief: TaskBrief) -> None:
        if not state.get("suspended"):
            return
        resume_next = brief.constraints.get("termination_resume_next_day")
        if resume_next is False:
            return
        resume_at = str(state.get("resume_at") or "").strip()
        if not resume_at:
            return
        try:
            when = datetime.fromisoformat(resume_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if now >= when.astimezone(timezone.utc):
                state["suspended"] = False
                state["day_index"] = int(state.get("day_index") or 1) + 1
                state.pop("resume_at", None)
                state.pop("wake_reason", None)
                state.pop("next_action", None)
                if is_skill_flow_brief(brief):
                    prepare_plan_recrawl(
                        state,
                        state.get("execution_plan") if isinstance(state.get("execution_plan"), dict) else None,
                        brief=brief,
                    )
        except Exception:
            return

    async def _heuristic_decide(
        self,
        brief: TaskBrief,
        snapshot: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
        stats = snapshot.get("interaction_stats") if isinstance(snapshot.get("interaction_stats"), dict) else {}
        validate_only = bool(brief.goals.get("outreach_validate_only"))
        leads = int(progress.get("leads_collected") or state.get("leads_collected") or 0)
        qualified = int(progress.get("leads_qualified") or state.get("leads_qualified") or 0)
        goal_count = effective_supervisor_goal_count(brief, state)
        target = int(progress.get("target_leads") or brief.goals.get("target_leads") or 50)

        if validate_only and state.get("outreach_validated"):
            return guard_supervisor_complete_decision(
                brief,
                state,
                {
                    "action": "complete",
                    "reasoning": f"[validate] 已确认匹配目标可执行 {state.get('last_validate_action') or 'outreach'}",
                    "params": {},
                    "goal_progress": {"leads_collected": leads, "leads_qualified": qualified, "target_leads": target},
                },
            )

        if not validate_only and goal_count >= target and not standalone_outreach_incomplete(brief, state):
            goal_label = "精准线索" if uses_qualified_leads_goal(brief) else "线索"
            return guard_supervisor_complete_decision(
                brief,
                state,
                {
                    "action": "complete",
                    "reasoning": f"已收集 {goal_count} 条{goal_label}，达到目标 {target}",
                    "params": {},
                    "goal_progress": {
                        "leads_collected": leads,
                        "leads_qualified": qualified,
                        "target_leads": target,
                    },
                },
            )

        if not state.get("crawl_done"):
            if state.get("evaluation_done") and target > 0 and qualified >= target:
                state["crawl_done"] = True
                state["qualified_target_reached"] = True

        if not state.get("crawl_done"):
            gate = crawl_evaluate_gate(brief, state)
            if gate.suspend:
                return self._make_suspend_decision(
                    state,
                    brief,
                    gate.reason,
                    completion_outcome=gate.completion_outcome,
                )
            if gate.force_evaluate:
                state["crawl_done"] = True
                if gate.reason:
                    state["crawl_evaluate_gate_reason"] = gate.reason
                return {
                    "action": "evaluate_leads",
                    "reasoning": gate.reason,
                    "params": {"platform": brief.platform or self.platform},
                    "goal_progress": {
                        "leads_collected": leads,
                        "comments_captured": int(state.get("comments_captured") or 0),
                        "target_leads": target,
                    },
                }

            crawl_failures = int(state.get("crawl_failures") or 0)
            if crawl_failures >= 1 and self._crawl_failure_should_suspend(brief, state):
                return self._make_suspend_decision(
                    state,
                    brief,
                    str(state.get("last_crawl_error") or "").strip()
                    or "抓取未成功，已挂起避免重复搜索触发风控；请检查登录/验证码后手动重试",
                )
            crawl_params = {
                "keyword": brief.keyword or "",
                "region": brief.region,
                **build_crawl_day_params(brief),
            }
            apply_crawl_video_limit_aliases(crawl_params, effective_crawl_video_limit(brief=brief))
            return {
                "action": "crawl_keyword",
                "skill_id": skill_id_from_brief(brief, "crawl_keyword"),
                "reasoning": "首轮抓取关键词视频评论",
                "params": crawl_params,
                "goal_progress": {
                    "leads_collected": leads,
                    "comments_captured": int(state.get("comments_captured") or 0),
                    "target_leads": target,
                },
            }

        if not state.get("evaluation_done") and requires_lead_evaluation(brief):
            gate = crawl_evaluate_gate(brief, state)
            if gate.suspend:
                return self._make_suspend_decision(
                    state,
                    brief,
                    gate.reason,
                    completion_outcome=gate.completion_outcome,
                )
            return {
                "action": "evaluate_leads",
                "reasoning": str(state.get("crawl_evaluate_gate_reason") or "").strip()
                or "抓取已完成，批量 LLM 评估入库评论是否符合线索标准",
                "params": {"platform": brief.platform or self.platform},
                "goal_progress": {
                    "leads_collected": leads,
                    "comments_captured": int(state.get("comments_captured") or 0),
                    "target_leads": target,
                },
            }

        if not state.get("stats_synced"):
            return {
                "action": "query_stats",
                "skill_id": skill_id_from_brief(brief, "query_stats"),
                "reasoning": "触达前同步今日 reply/follow/dm 配额",
                "params": {"platform": brief.platform or self.platform},
                "goal_progress": {
                    "leads_collected": leads,
                    "comments_captured": int(state.get("comments_captured") or 0),
                    "target_leads": target,
                },
            }

        if self._sandbox_runtime and self._sandbox_runtime.available:
            suggested = self._sandbox_runtime.suggest_outreach_action(stats, brief)
            if suggested in {"reply", "dm", "follow"}:
                decision = {
                    "action": suggested,
                    "skill_id": skill_id_from_brief(brief, suggested),
                    "reasoning": f"沙盒 helpers 建议优先 {suggested} 触达",
                    "params": {"keyword": brief.keyword},
                    "goal_progress": {
                        "leads_collected": leads,
                        "comments_captured": int(state.get("comments_captured") or 0),
                        "target_leads": target,
                    },
                }
                return await self._resolve_outreach_decision(
                    decision,
                    brief,
                    state,
                    action=suggested,
                    snapshot_stats=stats,
                )

        outreach_action, target_params, note = await resolve_outreach_action_with_policy_async(
            stats,
            brief,
            db_session=self.db_session,
            settings=self.settings,
            tenant_id=self.tenant_id,
            platform=brief.platform or self.platform,
            account_id=self.account_id,
            state=state,
            provider=self.provider,
        )
        if outreach_action and target_params:
            return {
                "action": outreach_action,
                "skill_id": skill_id_from_brief(brief, outreach_action),
                "reasoning": note,
                "params": target_params,
                "goal_progress": {
                    "leads_collected": leads,
                    "comments_captured": int(state.get("comments_captured") or 0),
                    "target_leads": target,
                },
            }
        if outreach_action is None and note == "今日触达配额已用尽":
            return self._quota_exhausted_decision(brief, state, stats)
        if outreach_action is None:
            return self._no_match_decision(
                brief,
                state,
                note or "已入库评论中无匹配待触达线索",
                stats,
            )

        if goal_count < target:
            return build_plan_incomplete_suspend_decision(brief, state)

        return guard_supervisor_complete_decision(
            brief,
            state,
            {
                "action": "complete",
                "reasoning": (
                    f"已收集 {goal_count} 条"
                    f"{'精准线索' if uses_qualified_leads_goal(brief) else '线索'}，达到目标 {target}"
                ),
                "params": {},
                "goal_progress": {
                    "leads_collected": leads,
                    "leads_qualified": effective_leads_qualified(state),
                    "target_leads": target,
                },
            },
        )

    async def _execute_action(
        self,
        *,
        action: str,
        params: dict[str, Any],
        session: AgentBrowserSession | None,
        brief: TaskBrief,
        dry_run: bool = False,
        state: dict[str, Any] | None = None,
        job_id: str = "",
        on_progress: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        if dry_run:
            return self._mock_action_result(action, params, brief, state or {})

        if (
            action in {"reply", "dm", "follow"}
            and bool(brief.goals.get("outreach_validate_only"))
        ):
            target_id = str(
                params.get("comment_id")
                or params.get("sec_uid")
                or params.get("user_id")
                or ""
            ).strip()
            return {
                "status": "completed",
                "validate_only": True,
                "action": action,
                "summary": f"[validate] 匹配成功，可执行 {action}" + (f" · {target_id}" if target_id else ""),
                "comment_id": params.get("comment_id"),
                "target_user_id": params.get("user_id") or params.get("sec_uid"),
                "reply_text": params.get("reply_text"),
                "message": params.get("message") or params.get("dm_template"),
                "params": params,
            }

        if action == "evaluate_leads":
            if self.db_session is None:
                return {"error": "数据库会话未初始化", "status": "failed"}
            try:
                result = await run_evaluate_leads_phase(
                    self.db_session,
                    self.settings,
                    tenant_id=self.tenant_id,
                    platform=brief.platform or self.platform,
                    brief=brief,
                    state=state or {},
                    provider=self.provider,
                )
                return {"status": "completed", **result}
            except ValueError as exc:
                return {"error": str(exc), "status": "failed"}

        if (
            action in CRAWL_SUPERVISOR_ACTIONS
            and (brief.platform or self.platform) == "douyin"
            and is_standalone_browse_brief(brief)
        ):
            from app.services.standalone_browse_adapter import run_standalone_browse_for_supervisor

            try:
                result = await asyncio.wait_for(
                    run_standalone_browse_for_supervisor(
                        self.settings,
                        tenant_id=self.tenant_id,
                        account_id=self.account_id,
                        brief=brief,
                        params=params,
                        action=action,
                        db_session=self.db_session,
                        state=state,
                        on_progress=on_progress,
                    ),
                    timeout=CRAWL_ACTION_TIMEOUT_SEC,
                )
                if result.get("error"):
                    result.setdefault("status", "failed")
                else:
                    result.setdefault("status", "completed")
                return result
            except asyncio.TimeoutError:
                return {
                    "error": f"{action} standalone 浏览超时（>{CRAWL_ACTION_TIMEOUT_SEC}s）",
                    "status": "failed",
                    "action": action,
                }
            except Exception as exc:
                return {"error": str(exc), "status": "failed", "action": action}

        skill_id = skill_id_from_brief(brief, action)
        if not skill_id:
            return {"error": f"未知动作: {action}", "status": "failed"}

        skill = self._skill_store.get(self.tenant_id, resolve_skill_id(skill_id))
        if skill is None:
            return {"error": f"技能不存在: {skill_id}", "status": "failed"}

        state = state if isinstance(state, dict) else {}
        merged = {
            **params,
            "platform": brief.platform or self.platform,
            "keyword": params.get("keyword") or brief.keyword,
            "region": params.get("region") or brief.region,
            "account_id": self.account_id,
            "provider": self.provider,
            "task_id": job_id or params.get("task_id") or params.get("job_id"),
            "job_id": job_id or params.get("job_id") or params.get("task_id"),
        }
        if self.agent_profile_id:
            merged["agent_profile_id"] = self.agent_profile_id
        if action in CRAWL_SUPERVISOR_ACTIONS:
            video_limit = effective_crawl_video_limit(brief=brief, params=params)
            apply_crawl_video_limit_aliases(merged, video_limit)
            merged.update(build_crawl_day_params(brief, merged))
            merged.pop("days", None)
            if is_skill_flow_brief(brief):
                merge_skill_flow_crawl_params(merged, brief=brief, state=state or {}, job_id=job_id)
            else:
                merged.setdefault("show_browser", False)
            if "force_refresh" not in merged:
                merged["force_refresh"] = bool(brief.goals.get("force_refresh", False))
            if "cache_ttl_hours" not in merged:
                merged["cache_ttl_hours"] = float(brief.goals.get("cache_ttl_hours") or 24)
            if action == "crawl_keyword" and not merged.get("keyword"):
                return {"error": "缺少 keyword", "status": "failed"}
            if action == "crawl_content_url" and not (merged.get("video_url") or merged.get("note_url")):
                return {"error": "缺少 video_url", "status": "failed"}
            if action == "crawl_profile" and not merged.get("profile_url"):
                return {"error": "缺少 profile_url", "status": "failed"}

        if action == "query_stats":
            for param_key, brief_key in (
                ("reply_limit", "daily_reply_limit"),
                ("follow_limit", "daily_follow_limit"),
                ("dm_limit", "daily_dm_limit"),
            ):
                val = brief.constraints.get(brief_key)
                if val is not None:
                    merged.setdefault(param_key, int(val))

        if action == "reply" and not merged.get("comment_id"):
            err = merge_outreach_params(
                merged,
                brief=brief,
                action="reply",
                db_session=self.db_session,
                settings=self.settings,
                tenant_id=self.tenant_id,
                platform=brief.platform or self.platform,
                account_id=self.account_id,
                state=state or {},
            )
            if err:
                return err

        if action in {"dm", "follow"} and not (merged.get("sec_uid") or merged.get("user_id")):
            err = merge_outreach_params(
                merged,
                brief=brief,
                action=action,
                db_session=self.db_session,
                settings=self.settings,
                tenant_id=self.tenant_id,
                platform=brief.platform or self.platform,
                account_id=self.account_id,
                state=state or {},
            )
            if err:
                return err

        if action in {"reply", "dm", "follow"}:
            merged.setdefault("prefer_human_ui", bool(brief.goals.get("ui_first", False)))
            merged.setdefault("prefer_ui_reply", bool(brief.goals.get("ui_first", False)))
            merged.setdefault("ui_first", bool(brief.goals.get("ui_first", False)))
            if (brief.platform or self.platform) == "douyin" and bool(brief.goals.get("ui_first", False)):
                if action in {"dm", "follow"}:
                    merged.setdefault("warm_outreach", True)
                if action == "reply":
                    merged.setdefault("warm_publish", True)
            if (brief.platform or self.platform) == "xiaohongshu" and bool(brief.goals.get("ui_first", False)):
                if action in {"follow", "reply"}:
                    merged.setdefault("warm_outreach", True)
                if action == "reply":
                    merged.setdefault("warm_publish", True)
        if session is None and action not in CRAWL_SUPERVISOR_ACTIONS:
            return {"error": "浏览器会话未初始化", "status": "failed"}

        if action in CRAWL_SUPERVISOR_ACTIONS:
            timeout_sec = CRAWL_ACTION_TIMEOUT_SEC
        elif action in {"reply", "dm", "follow"}:
            timeout_sec = OUTREACH_ACTION_TIMEOUT_SEC
        else:
            timeout_sec = None
        if (
            action in CRAWL_SUPERVISOR_ACTIONS
            and brief.goals.get("visible_crawl_once")
            and not (state or {}).get("visible_crawl_done")
        ):
            merged["show_browser"] = True
            merged["force_refresh"] = True

        async def _run_crawl_via_runner() -> dict[str, Any]:
            runner = SkillRunnerService(
                self.settings,
                self.tenant_id,
                self.platform,
                account_id=self.account_id,
                db_session=self.db_session,
            )
            show = bool(merged.get("show_browser", show_browser(brief)))
            return await runner.execute(
                skill.id,
                merged,
                headless=not show,
                agent_fallback=False,
                provider=str(merged.get("provider") or self.provider),
                timeout_seconds=timeout_sec or CRAWL_ACTION_TIMEOUT_SEC,
                browser_session=session,
            )

        async def _run_with_session() -> dict[str, Any]:
            await session.ensure_started()
            pw = PlaywrightToolExecutor(session, self.settings)
            executor = SkillExecutor(
                self.settings,
                self.tenant_id,
                self.platform,
                session,
                pw,
                db_session=self.db_session,
            )
            return await executor.execute(skill, merged)

        try:
            if action in CRAWL_SUPERVISOR_ACTIONS:
                result = await _run_crawl_via_runner()
            elif timeout_sec:
                result = await asyncio.wait_for(_run_with_session(), timeout=timeout_sec)
            else:
                result = await _run_with_session()
            if result.get("error"):
                result.setdefault("status", "failed")
            else:
                result.setdefault("status", "completed")
            err_blob = str(result.get("error") or result.get("diagnostic") or "")
            if session is not None and "has been closed" in err_blob.lower():
                with contextlib.suppress(Exception):
                    await session._discard_dead_browser()
            return result
        except asyncio.TimeoutError:
            try:
                from app.services.playwright_pool import PlaywrightPool

                await PlaywrightPool.get().shutdown()
            except Exception:
                pass
            return {
                "error": f"{action} 执行超时（>{timeout_sec or CRAWL_ACTION_TIMEOUT_SEC}s）",
                "status": "failed",
                "action": action,
            }
        except Exception as exc:
            err = str(exc)
            if session is not None and "has been closed" in err.lower():
                with contextlib.suppress(Exception):
                    await session._discard_dead_browser()
            return {"error": err, "status": "failed", "action": action}

    def _mock_action_result(
        self,
        action: str,
        params: dict[str, Any],
        brief: TaskBrief,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """dry_run：模拟 Skill 结果，不启动浏览器、不抓真实数据。"""
        day = int(state.get("day_index") or 1)
        if action in CRAWL_SUPERVISOR_ACTIONS:
            captured = int(brief.goals.get("mock_crawl_batch") or 80)
            return {
                "status": "completed",
                "dry_run": True,
                "summary": f"[dry_run] 模拟抓取 {captured} 条评论（第 {day} 天）",
                "total_comments_captured": captured,
                "videos_processed": int(
                    params.get("crawl_video_limit")
                    or params.get("video_limit")
                    or params.get("content_limit")
                    or params.get("limit")
                    or 0
                ),
            }
        if action == "query_stats":
            sim = state.get("simulated_stats")
            if isinstance(sim, dict):
                return {"status": "completed", "dry_run": True, "summary": "[dry_run] 模拟台账", "result": sim}
            return {
                "status": "completed",
                "dry_run": True,
                "summary": "[dry_run] 查询互动台账",
                "result": {
                    "reply": {"count": 5, "limit": 5, "can_do": False},
                    "dm": {"count": 3, "limit": 3, "can_do": False},
                    "follow": {"count": 3, "limit": 3, "can_do": False},
                },
            }
        if action == "evaluate_leads":
            return {
                "status": "completed",
                "dry_run": True,
                "summary": "[dry_run] 模拟 LLM 评估评论",
                "evaluated": 20,
                "qualified": 5,
            }
        if action in {"reply", "dm", "follow"}:
            seq = int(state.get("leads_collected") or 0) + 1
            return {
                "status": "completed",
                "dry_run": True,
                "summary": f"[dry_run] 模拟 {action} 触达 1 条",
                "comment_id": f"dry-cmt-{seq}",
                "target_user_id": f"dry-user-{seq}",
                "target_nickname": f"模拟用户{seq}",
            }
        if action == "query_comments":
            return {
                "status": "completed",
                "dry_run": True,
                "summary": "[dry_run] 模拟查询已存评论",
                "result": {"count": 10},
            }
        return {"status": "completed", "dry_run": True, "summary": f"[dry_run] 跳过 {action}"}

    def _mark_suspended(
        self,
        state: dict[str, Any],
        brief: TaskBrief,
        reason: str,
        *,
        resume_at: str | None = None,
        completion_outcome: str | None = None,
    ) -> None:
        diag = state.get("page_diagnosis")
        if isinstance(diag, dict) and str(diag.get("user_title") or "").strip():
            reason = str(diag["user_title"]).strip()
        apply_suspend_state(
            state,
            brief,
            reason,
            resume_at=resume_at,
            completion_outcome=completion_outcome,
        )
        if isinstance(diag, dict):
            steps = diag.get("user_steps")
            if isinstance(steps, list) and steps:
                state["next_action"] = "\n".join(
                    f"{idx + 1}. {step}" for idx, step in enumerate(steps) if str(step).strip()
                )
            summary = str(diag.get("user_summary") or "").strip()
            if summary and not str(state.get("wake_reason") or "").strip():
                state["wake_reason"] = summary

    async def _try_standalone_auto_continue(
        self,
        *,
        brief: TaskBrief,
        state: dict[str, Any],
        reasoning: str,
        on_progress: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None,
    ) -> bool:
        if not standalone_can_auto_continue(brief, state):
            return False
        prepare_standalone_auto_continue(state, brief)
        await self._emit(
            on_progress,
            "status",
            {
                "message": f"Standalone 自动续扫（未达目标）：{reasoning[:96]}",
                "auto_continue": True,
            },
        )
        await asyncio.sleep(MIN_CYCLE_INTERVAL_SEC)
        return True

    async def _maybe_run_page_diagnosis(
        self,
        *,
        state: dict[str, Any],
        brief: TaskBrief,
        action: str,
        skill_result: dict[str, Any],
        session: Any | None,
        dry_run: bool,
    ) -> None:
        if dry_run or not getattr(self.settings, "page_diagnosis_enabled", True):
            return
        if state.get("page_diagnosis"):
            return
        try:
            from app.services.page_diagnosis.mappers.registry import infer_implementation, normalize_failure
            from app.services.page_diagnosis.providers import build_snapshot_provider
            from app.services.page_diagnosis.reporter import (
                CrawlFailureReporter,
                apply_diagnosis_to_state,
                should_diagnose_failure,
            )

            page = None
            if session is not None:
                with contextlib.suppress(Exception):
                    await session.ensure_started()
                    page = getattr(session, "page", None)

            implementation = infer_implementation(skill_result, has_page=page is not None)
            signal = normalize_failure(
                platform=brief.platform or self.platform,
                operation=action,
                implementation=implementation,
                skill_result=skill_result,
            )
            if not should_diagnose_failure(
                skill_result=skill_result,
                signal=signal,
                state=state,
                action=action,
            ):
                return

            provider = build_snapshot_provider(
                platform=brief.platform or self.platform,
                implementation=implementation,
                page=page,
                settings=self.settings,
                tenant_id=self.tenant_id,
                job_id=str(state.get("job_id") or "").strip() or None,
            )
            reporter = CrawlFailureReporter(self.settings, self.tenant_id)
            diagnosis = await reporter.report(
                platform=brief.platform or self.platform,
                operation=action,
                skill_result=skill_result,
                snapshot_provider=provider,
                page=page,
                job_id=str(state.get("job_id") or "").strip() or None,
            )
            if diagnosis is not None and diagnosis.confidence >= 0.65:
                apply_diagnosis_to_state(state, diagnosis)
        except Exception:
            return

    def _make_suspend_decision(
        self,
        state: dict[str, Any],
        brief: TaskBrief,
        reason: str,
        *,
        completion_outcome: str | None = None,
    ) -> dict[str, Any]:
        leads = int(state.get("leads_collected") or 0)
        target = int(brief.goals.get("target_leads") or 50)
        resume_at = _default_resume_at()
        decision = {
            "action": "suspend",
            "reasoning": reason,
            "resume_at": resume_at,
            "params": {},
            "goal_progress": {"leads_collected": leads, "target_leads": target},
        }
        if completion_outcome:
            decision["completion_outcome"] = completion_outcome
        return decision

    @staticmethod
    def _track_loop_guards(
        state: dict[str, Any],
        *,
        action: str,
        fp_before: str,
        fp_after: str,
    ) -> None:
        progressed = fp_after != fp_before
        if progressed:
            state["stale_cycles"] = 0
            state["_repeat_action_count"] = 0
        elif action in PROGRESS_ACTIONS or action == "query_stats":
            state["stale_cycles"] = int(state.get("stale_cycles") or 0) + 1

        if action == state.get("_repeat_action"):
            state["_repeat_action_count"] = int(state.get("_repeat_action_count") or 0) + 1
        else:
            state["_repeat_action"] = action
            state["_repeat_action_count"] = 1

        state["_last_fingerprint"] = fp_after

    def _update_state(
        self,
        state: dict[str, Any],
        action: str,
        skill_result: dict[str, Any],
        brief: TaskBrief,
        *,
        dry_run: bool = False,
        params: dict[str, Any] | None = None,
    ) -> None:
        state["last_action"] = action
        state["last_at"] = _utc_now_iso()
        ok = not skill_result.get("error") and str(skill_result.get("status", "")).lower() != "failed"
        sandbox_active = bool(self._sandbox_runtime and self._sandbox_runtime.available)

        revisit_under_crawl = (
            action == "crawl_content_url"
            and bool(
                (params or {}).get("_revisit_under_crawl_step")
                or state.get("_revisit_under_crawl_step")
            )
        )
        if revisit_under_crawl:
            content_id = str(
                (params or {}).get("_revisit_content_id")
                or state.get("_revisit_content_id")
                or ""
            ).strip()
            if not content_id:
                from app.platforms.douyin.js_constants import _extract_aweme_id

                video_url = str((params or {}).get("video_url") or skill_result.get("video_url") or "")
                content_id = _extract_aweme_id(video_url) or ""
            if content_id:
                mark_url_revisited(state, content_id)
            state.pop("_revisit_under_crawl_step", None)
            state.pop("_revisit_content_id", None)
            captured = count_crawl_from_skill_result(skill_result)
            if captured:
                state["comments_captured"] = int(state.get("comments_captured") or 0) + captured
            session_persisted = int(skill_result.get("comments_persisted") or 0)
            if session_persisted > 0:
                state["comments_persisted"] = int(state.get("comments_persisted") or 0) + session_persisted
            if ok or str(skill_result.get("status", "")).lower() == "partial":
                record_crawl_round_without_evaluation(state)
            if self.db_session is not None and not dry_run and (ok or captured):
                try:
                    persisted = persist_crawl_skill_result(
                        self.db_session,
                        self.settings,
                        tenant_id=self.tenant_id,
                        platform=brief.platform or self.platform,
                        skill_result=skill_result,
                        source_job_id=str(state.get("job_id") or "").strip() or None,
                        source_keyword=str(brief.keyword or skill_result.get("keyword") or "").strip() or None,
                    )
                    state["comments_persisted"] = int(state.get("comments_persisted") or 0) + persisted
                    merge_job_persisted_comment_ids(state, skill_result)
                except Exception:
                    pass
            execution_plan = state.get("execution_plan")
            if isinstance(execution_plan, dict):
                state["execution_plan"] = advance_supervisor_plan(
                    execution_plan,
                    action=action,
                    ok=ok or str(skill_result.get("status", "")).lower() == "partial",
                    state=state,
                    brief=brief,
                )
            return

        if action in CRAWL_SUPERVISOR_ACTIONS and skill_result.get("standalone_browse") and ok:
            batch_precise = int(skill_result.get("precise_lead_count") or 0)
            state["evaluation_done"] = True
            from app.services.task_round_service import persisted_precise_comment_count

            persisted = persisted_precise_comment_count(state)
            if persisted > 0:
                state["leads_qualified"] = persisted
            else:
                state["leads_qualified"] = max(int(state.get("leads_qualified") or 0), batch_precise)
            state.pop("standalone_session_qualified_base", None)
            outreach_leads = _extract_outreach_leads(skill_result)
            executed = int(skill_result.get("outreach_executed_count") or 0)
            if executed:
                state["outreach_executed_count"] = max(
                    int(state.get("outreach_executed_count") or 0),
                    executed,
                )
            if outreach_leads:
                _add_leads_to_state(brief, state, outreach_leads)
            elif executed:
                _add_leads_to_state(brief, state, executed)
            elif batch_precise and bool(brief.goals.get("outreach_validate_only")):
                _add_leads_to_state(brief, state, batch_precise)

        if action == "crawl_keyword" and ok and not dry_run and not skill_result.get("standalone_browse"):
            valid, err_msg, comment_count = validate_crawl_skill_result(skill_result)
            if not valid:
                ok = False
                skill_result["status"] = "failed"
                skill_result["error"] = err_msg
                state["last_crawl_error"] = err_msg
            elif comment_count:
                skill_result["total_comments_captured"] = comment_count

        if action in {"reply", "dm", "follow"} and not ok and not dry_run:
            err_text = str(skill_result.get("error") or skill_result.get("summary") or "")
            if "无匹配" in err_text and self._should_resume_crawl_on_no_match(brief, state):
                plan = state.get("execution_plan")
                if isinstance(plan, dict):
                    from app.services.supervisor_crawl_helpers import prepare_plan_recrawl

                    prepare_plan_recrawl(state, plan, brief=brief)
                    state.pop("evaluation_done", None)
                    state.pop("leads_qualified", None)
                    state["stale_cycles"] = 0

        execution_plan = state.get("execution_plan")
        if isinstance(execution_plan, dict):
            state["execution_plan"] = advance_supervisor_plan(
                execution_plan,
                action=action,
                ok=ok,
                state=state,
                brief=brief,
            )

        if action == "crawl_keyword" and ok:
            saved_search = str(skill_result.get("search_url") or "").strip()
            if saved_search and "/search/" in saved_search.lower():
                state["standalone_search_url"] = saved_search
            record_crawl_round_without_evaluation(state)
            captured = _extract_crawl_captured_count(skill_result)
            videos_processed = int(skill_result.get("videos_processed") or 0)
            target_leads = int(brief.goals.get("target_leads") or 0)
            leads_now = int(state.get("leads_collected") or 0)
            leads_qualified = int(state.get("leads_qualified") or 0)
            gate = crawl_evaluate_gate(brief, state)
            search_phase_ok = crawl_search_phase_succeeded(skill_result)
            skill_flow_need_more = (
                is_skill_flow_brief(brief)
                and not skill_result.get("standalone_browse")
                and captured <= 0
                and videos_processed >= 0
                and not skill_result.get("crawl_search_exhausted")
                and (target_leads <= 0 or leads_now < target_leads)
                and not (target_leads > 0 and leads_qualified >= target_leads)
                and (
                    videos_processed > 0
                    or bool(state.get("watched_content_ids"))
                    or search_phase_ok
                )
                and not gate.force_evaluate
                and not gate.suspend
            )
            standalone_need_more = (
                skill_result.get("standalone_browse")
                and bool(skill_result.get("standalone_need_more"))
                and not skill_result.get("target_reached")
                and not skill_result.get("crawl_search_exhausted")
                and (target_leads <= 0 or leads_qualified < target_leads)
            )
            if target_leads > 0 and leads_qualified >= target_leads:
                state["crawl_done"] = True
                state["qualified_target_reached"] = True
                standalone_need_more = False
            if gate.force_evaluate:
                state["crawl_done"] = True
                skill_flow_need_more = False
                standalone_need_more = False
                if gate.reason:
                    state["crawl_evaluate_gate_reason"] = gate.reason
            elif standalone_need_more:
                state.pop("crawl_done", None)
                vp = int(skill_result.get("videos_processed") or 0)
                if vp > 0:
                    state["standalone_browse_offset"] = int(state.get("standalone_browse_offset") or 0) + vp
                state["last_crawl_error"] = (
                    str(skill_result.get("diagnostic") or "")[:200]
                    or "本批视频未找到足够精准线索，继续浏览下一个视频"
                )
                execution_plan = state.get("execution_plan")
                if isinstance(execution_plan, dict):
                    steps = execution_plan.get("steps")
                    if isinstance(steps, list):
                        for step in steps:
                            if not isinstance(step, dict):
                                continue
                            step_action = str(step.get("action") or "")
                            if step_action == "crawl_keyword":
                                step["status"] = "in_progress"
                            elif step_action in {"evaluate_leads", "query_stats", "complete", *OUTREACH_LOOP_ACTIONS}:
                                step["status"] = "pending"
                        execution_plan["current_index"] = 0
                        state["execution_plan"] = execution_plan
            elif skill_flow_need_more:
                state.pop("crawl_done", None)
                if search_phase_ok and videos_processed <= 0:
                    state["last_crawl_error"] = "搜索已成功，本批未抓到评论，继续浏览更多视频"
                else:
                    state["last_crawl_error"] = "本批视频未抓到匹配评论，继续浏览更多视频"
                execution_plan = state.get("execution_plan")
                if isinstance(execution_plan, dict):
                    steps = execution_plan.get("steps")
                    if isinstance(steps, list):
                        for step in steps:
                            if not isinstance(step, dict):
                                continue
                            step_action = str(step.get("action") or "")
                            if step_action == "crawl_keyword":
                                step["status"] = "in_progress"
                            elif step_action in {"evaluate_leads", "query_stats", "complete", *OUTREACH_LOOP_ACTIONS}:
                                step["status"] = "pending"
                        execution_plan["current_index"] = 0
                        state["execution_plan"] = execution_plan
                        state.pop("evaluation_done", None)
            else:
                state["crawl_done"] = True
                state["crawl_failures"] = 0
                if params and params.get("show_browser"):
                    state["visible_crawl_done"] = True
                if captured:
                    state["comments_captured"] = int(state.get("comments_captured") or 0) + captured
            raw_scanned = int(skill_result.get("raw_comments_scanned") or 0)
            if raw_scanned:
                state["raw_comments_scanned"] = int(state.get("raw_comments_scanned") or 0) + raw_scanned
            videos_processed = int(skill_result.get("videos_processed") or 0)
            if videos_processed:
                state["videos_processed"] = int(state.get("videos_processed") or 0) + videos_processed
            session_persisted = int(skill_result.get("comments_persisted") or 0)
            if session_persisted > 0:
                state["comments_persisted"] = int(state.get("comments_persisted") or 0) + session_persisted
            outreach_leads = _extract_outreach_leads(skill_result)
            if outreach_leads:
                _add_leads_to_state(brief, state, outreach_leads)
            watched = skill_result.get("watched_content_ids")
            watched_job_id = str(skill_result.get("watched_job_id") or state.get("job_id") or "").strip()
            task_job_id = str(state.get("job_id") or "").strip()
            if (
                isinstance(watched, list)
                and watched
                and videos_processed > 0
                and not skill_result.get("cache_replay")
                and (not task_job_id or not watched_job_id or watched_job_id == task_job_id)
            ):
                existing = {
                    str(x).strip() for x in (state.get("watched_content_ids") or []) if str(x).strip()
                }
                existing.update(str(x).strip() for x in watched if str(x).strip())
                state["watched_content_ids"] = sorted(existing)[-500:]
                content_existing = {
                    str(x).strip() for x in (state.get("job_content_ids") or []) if str(x).strip()
                }
                content_existing.update(str(x).strip() for x in watched if str(x).strip())
                state["job_content_ids"] = sorted(content_existing)[-500:]
            if skill_result.get("crawl_search_exhausted") and videos_processed > 0 and not skill_result.get("cache_replay"):
                state["crawl_search_exhausted"] = True
            else:
                state.pop("crawl_search_exhausted", None)
            if skill_result.get("outreach_quota_exhausted"):
                state["outreach_quota_exhausted"] = True
            else:
                state.pop("outreach_quota_exhausted", None)
            if self.db_session is not None and not dry_run:
                try:
                    persisted = persist_crawl_skill_result(
                        self.db_session,
                        self.settings,
                        tenant_id=self.tenant_id,
                        platform=brief.platform or self.platform,
                        skill_result=skill_result,
                        source_job_id=str(state.get("job_id") or "").strip() or None,
                        source_keyword=str(brief.keyword or skill_result.get("keyword") or "").strip() or None,
                    )
                    state["comments_persisted"] = int(state.get("comments_persisted") or 0) + persisted
                    merge_job_persisted_comment_ids(state, skill_result)
                except Exception:
                    pass

        if action in {"crawl_profile", "crawl_content_url"} and ok:
            if skill_result.get("standalone_browse"):
                batch_precise = int(skill_result.get("precise_lead_count") or 0)
                state["evaluation_done"] = True
                state["leads_qualified"] = int(state.get("leads_qualified") or 0) + batch_precise
                outreach_leads = _extract_outreach_leads(skill_result)
                executed = int(skill_result.get("outreach_executed_count") or 0)
                if outreach_leads:
                    _add_leads_to_state(brief, state, outreach_leads)
                elif executed:
                    _add_leads_to_state(brief, state, executed)
            record_crawl_round_without_evaluation(state)
            captured = count_crawl_from_skill_result(skill_result)
            videos_processed = int(skill_result.get("videos_processed") or 0)
            state["crawl_done"] = True
            state["crawl_failures"] = 0
            if params and params.get("show_browser"):
                state["visible_crawl_done"] = True
            if captured:
                state["comments_captured"] = int(state.get("comments_captured") or 0) + captured
            if videos_processed:
                state["videos_processed"] = int(state.get("videos_processed") or 0) + videos_processed
            session_persisted = int(skill_result.get("comments_persisted") or 0)
            if session_persisted > 0:
                state["comments_persisted"] = int(state.get("comments_persisted") or 0) + session_persisted
            watched = skill_result.get("watched_content_ids")
            watched_job_id = str(skill_result.get("watched_job_id") or state.get("job_id") or "").strip()
            task_job_id = str(state.get("job_id") or "").strip()
            if (
                isinstance(watched, list)
                and watched
                and videos_processed > 0
                and not skill_result.get("cache_replay")
                and (not task_job_id or not watched_job_id or watched_job_id == task_job_id)
            ):
                existing = {
                    str(x).strip() for x in (state.get("watched_content_ids") or []) if str(x).strip()
                }
                existing.update(str(x).strip() for x in watched if str(x).strip())
                state["watched_content_ids"] = sorted(existing)[-500:]
            # 主页/单链一轮即结束，避免 0 评论时 evaluate 后无限重抓
            state["crawl_search_exhausted"] = True
            if captured <= 0 and videos_processed <= 0:
                err_text = " ".join(
                    str(skill_result.get(k) or "")
                    for k in ("error", "diagnostic", "summary")
                ).strip()
                if err_text:
                    state["last_crawl_error"] = err_text[:500]
            elif captured <= 0 and videos_processed > 0:
                err_text = str(skill_result.get("summary") or skill_result.get("diagnostic") or "").strip()
                if err_text:
                    state["last_crawl_error"] = err_text[:500]
            if self.db_session is not None and not dry_run:
                try:
                    persisted = persist_crawl_skill_result(
                        self.db_session,
                        self.settings,
                        tenant_id=self.tenant_id,
                        platform=brief.platform or self.platform,
                        skill_result=skill_result,
                        source_job_id=str(state.get("job_id") or "").strip() or None,
                        source_keyword=str(brief.keyword or skill_result.get("keyword") or "").strip() or None,
                    )
                    state["comments_persisted"] = int(state.get("comments_persisted") or 0) + persisted
                    merge_job_persisted_comment_ids(state, skill_result)
                except Exception:
                    pass

        if action == "crawl_keyword" and not ok:
            state["crawl_failures"] = int(state.get("crawl_failures") or 0) + 1
            if params and params.get("show_browser"):
                state["visible_crawl_done"] = True
            err_text = " ".join(
                str(skill_result.get(k) or "")
                for k in ("error", "diagnostic", "summary")
            ).strip()
            if err_text:
                state["last_crawl_error"] = err_text[:500]
            if any(token in err_text for token in ("verify_check", "验证码", "人机验证", "风控")):
                state["crawl_risk_blocked"] = True

        if action in {"reply", "dm", "follow"}:
            if skill_result.get("validate_only"):
                state["outreach_validated"] = True
                state["last_validate_action"] = action
                state["last_validate_at"] = _utc_now_iso()
            elif ok and not sandbox_active:
                _add_leads_to_state(brief, state, 1)
            if ok and action in {"dm", "follow"}:
                user_key = str(
                    (params or {}).get("sec_uid")
                    or (params or {}).get("user_id")
                    or skill_result.get("sec_uid")
                    or skill_result.get("user_id")
                    or ""
                ).strip()
                if user_key:
                    touched = state.get("outreach_touched_user_ids")
                    if not isinstance(touched, list):
                        touched = []
                    if user_key not in touched:
                        touched.append(user_key)
                    state["outreach_touched_user_ids"] = touched[-200:]
            if not ok and action == "reply":
                failed_id = str(
                    (params or {}).get("comment_id")
                    or skill_result.get("comment_id")
                    or ""
                ).strip()
                if failed_id:
                    failed = state.get("failed_comment_ids")
                    if not isinstance(failed, list):
                        failed = []
                    if failed_id not in failed:
                        failed.append(failed_id)
                    state["failed_comment_ids"] = failed[-100:]
            if dry_run:
                append_memory_ledger_action(
                    state,
                    action=action,
                    ok=ok,
                    summary=str(skill_result.get("summary") or ""),
                    comment_id=str(skill_result.get("comment_id") or "").strip() or None,
                    target_user_id=str(skill_result.get("target_user_id") or "").strip() or None,
                    target_nickname=str(skill_result.get("target_nickname") or "").strip() or None,
                    reply_text=str(skill_result.get("reply_text") or "").strip() or None,
                )

        if action == "evaluate_leads" and ok:
            state["evaluation_done"] = True
            reset_crawl_evaluate_gate_state(state)
            target_leads = int(brief.goals.get("target_leads") or 0)
            qualified = int(state.get("leads_qualified") or 0)
            if target_leads > 0 and qualified >= target_leads:
                state["crawl_done"] = True
                state["qualified_target_reached"] = True

        if action == "query_stats" and ok:
            result = skill_result.get("result")
            if isinstance(result, dict):
                state["last_stats"] = result
            state["stats_synced"] = True

        validate_only = bool(brief.goals.get("outreach_validate_only"))
        if sandbox_active and self._sandbox_runtime is not None and not skill_result.get("validate_only"):
            self._sandbox_runtime.record_action(
                action=action,
                skill_result=skill_result,
                brief=brief,
                params=params or {},
                dry_run=dry_run,
            )
            summary = self._sandbox_runtime.get_summary()
            if not validate_only:
                outreach_ok = int(summary.get("outreach_ok") or 0)
                if outreach_ok > 0:
                    state["leads_collected"] = outreach_ok
                    if round_loop_enabled(brief):
                        ensure_round_state(brief, state)
                        state["round_leads_collected"] = outreach_ok
            if int(summary.get("crawl_comments_total") or 0) > 0 and not bool(brief.goals.get("force_refresh")):
                state["crawl_done"] = True

    def _goal_reached(self, brief: TaskBrief, state: dict[str, Any]) -> bool:
        if bool(brief.goals.get("outreach_validate_only")):
            return bool(state.get("outreach_validated"))
        if round_loop_enabled(brief):
            return goal_reached_for_current_round(brief, state)
        target = int(brief.goals.get("target_leads") or 0)
        if target <= 0:
            return False
        if is_standalone_browse_brief(brief):
            if effective_leads_qualified(state) < target:
                return False
            return not standalone_outreach_incomplete(brief, state)
        return effective_supervisor_goal_count(brief, state) >= target

    def _resolve_llm(self) -> tuple[Any, str]:
        factory = AIClientFactory(self.settings)
        return factory.llm_client(), factory.llm_model()

    @staticmethod
    def _cycle_record(cycle: int, decision: dict[str, Any], skill_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "cycle": cycle,
            "at": _utc_now_iso(),
            "action": decision.get("action"),
            "reasoning": decision.get("reasoning"),
            "params": decision.get("params"),
            "goal_progress": decision.get("goal_progress"),
            "result_status": skill_result.get("status"),
            "result_summary": skill_result.get("summary") or skill_result.get("message") or skill_result.get("error"),
            "ok": not skill_result.get("error"),
        }

    @staticmethod
    async def _emit(
        callback: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        if callback is None:
            return
        maybe = callback(event_type, data)
        if asyncio.iscoroutine(maybe):
            await maybe
