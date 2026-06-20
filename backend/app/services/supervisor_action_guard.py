from __future__ import annotations

from typing import Any

from app.services.supervisor_outreach import (
    actions_on_match_from_brief,
    outreach_quotas_exhausted,
    outreach_stats_ready,
)
from app.services.supervisor_crawl_helpers import crawl_evaluate_gate
from app.services.task_brief_service import TaskBrief, is_skill_flow_brief
from app.services.task_execution_plan import guard_supervisor_complete_decision
from app.services.supervisor_crawl_helpers import build_crawl_action_params
from app.services.manual_acquisition_service import manual_acquisition_mode

OUTREACH_ACTIONS = frozenset({"reply", "dm", "follow"})


def _evaluate_leads_redirect(
    decision: dict[str, Any],
    brief: TaskBrief,
    *,
    reasoning: str,
) -> dict[str, Any]:
    return {
        **decision,
        "action": "evaluate_leads",
        "reasoning": reasoning,
        "params": {"platform": brief.platform or "douyin"},
    }


def _needs_lead_evaluation(brief: TaskBrief) -> bool:
    if manual_acquisition_mode(brief):
        return True
    return is_skill_flow_brief(brief)


requires_lead_evaluation = _needs_lead_evaluation


def _primary_crawl_action(brief: TaskBrief) -> str:
    mode = manual_acquisition_mode(brief)
    if mode == "single_video":
        return "crawl_content_url"
    if mode == "account_home":
        return "crawl_profile"
    return "crawl_keyword"


def _guard_crawl_supervisor_action(
    decision: dict[str, Any],
    *,
    action: str,
    brief: TaskBrief,
    state: dict[str, Any],
) -> dict[str, Any]:
    if not state.get("crawl_done"):
        gate = crawl_evaluate_gate(brief, state)
        if gate.suspend:
            suspended = {
                **decision,
                "action": "suspend",
                "reasoning": gate.reason,
                "params": {},
            }
            if gate.completion_outcome:
                suspended["completion_outcome"] = gate.completion_outcome
            return suspended
        if gate.force_evaluate:
            return _evaluate_leads_redirect(decision, brief, reasoning=gate.reason)
    if state.get("crawl_done"):
        if not state.get("evaluation_done") and _needs_lead_evaluation(brief):
            return _evaluate_leads_redirect(
                decision,
                brief,
                reasoning=f"系统拦截：已完成抓取，须先 LLM 评估评论，禁止重复 {action}",
            )
        return {
            **decision,
            "action": "query_stats" if not state.get("stats_synced") else "query_comments",
            "reasoning": f"系统拦截：已完成抓取，禁止重复 {action}",
            "params": {"platform": brief.platform} if not state.get("stats_synced") else {},
        }
    return decision


def configured_outreach_actions(brief: TaskBrief) -> set[str]:
    actions: set[str] = set()
    for item in actions_on_match_from_brief(brief):
        if isinstance(item, dict):
            action = str(item.get("type") or "").strip().lower()
            if action in OUTREACH_ACTIONS:
                actions.add(action)
    priority = brief.constraints.get("outreach_priority")
    if isinstance(priority, list) and priority:
        allowed = {str(x).strip().lower() for x in priority if str(x).strip()}
        allowed = {x for x in allowed if x in OUTREACH_ACTIONS}
        if allowed:
            actions = actions & allowed if actions else allowed
    elif isinstance(priority, str) and priority.strip():
        allowed = {priority.strip().lower()} & OUTREACH_ACTIONS
        if allowed:
            actions = actions & allowed if actions else allowed
    return actions or {"reply"}


def guard_supervisor_action(
    decision: dict[str, Any],
    *,
    brief: TaskBrief,
    state: dict[str, Any],
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """硬裁决 Supervisor 动作，避免 LLM 在允许动作范围内偏离任务。"""
    action = str(decision.get("action") or "").strip().lower()
    if not action:
        return {"action": "fail", "reasoning": "缺少 action", "params": {}}

    if action == "complete":
        return guard_supervisor_complete_decision(brief, state, decision)

    if action == "crawl_keyword":
        return _guard_crawl_supervisor_action(decision, action=action, brief=brief, state=state)

    if action in {"crawl_content_url", "crawl_profile"}:
        return _guard_crawl_supervisor_action(decision, action=action, brief=brief, state=state)

    if action == "query_stats":
        if (
            state.get("crawl_done")
            and not state.get("evaluation_done")
            and _needs_lead_evaluation(brief)
        ):
            return _evaluate_leads_redirect(
                decision,
                brief,
                reasoning="系统拦截：同步配额前必须先 LLM 评估入库评论",
            )
        return decision

    if action in OUTREACH_ACTIONS:
        if not state.get("crawl_done"):
            crawl_action = _primary_crawl_action(brief)
            return {
                **decision,
                "action": crawl_action,
                "reasoning": f"系统拦截：未完成抓取，禁止直接 {action}",
                "params": build_crawl_action_params(brief, crawl_action),
            }
        if not state.get("evaluation_done") and _needs_lead_evaluation(brief):
            return {
                **decision,
                "action": "evaluate_leads",
                "reasoning": f"系统拦截：触达前必须先 LLM 评估评论，禁止直接 {action}",
                "params": {"platform": brief.platform},
            }
        if not state.get("stats_synced"):
            return {
                **decision,
                "action": "query_stats",
                "reasoning": f"系统拦截：触达前必须先同步配额，禁止直接 {action}",
                "params": {"platform": brief.platform},
            }
        allowed = configured_outreach_actions(brief)
        if action not in allowed:
            fallback = next(iter(allowed))
            return {
                **decision,
                "action": fallback,
                "reasoning": f"系统拦截：任务配置不允许 {action}，改为 {fallback}",
                "params": {},
            }
        merged_stats = stats if isinstance(stats, dict) else {}
        if outreach_stats_ready(merged_stats, brief):
            bucket = merged_stats.get(action) if isinstance(merged_stats.get(action), dict) else {}
            can_do = bucket.get("can_do")
            if can_do is False:
                if outreach_quotas_exhausted(merged_stats, brief):
                    return {
                        **decision,
                        "action": "suspend",
                        "reasoning": "系统拦截：今日触达配额已用尽",
                        "params": {},
                        "completion_outcome": "quota_exhausted",
                    }
                for candidate in allowed:
                    cand_bucket = merged_stats.get(candidate) if isinstance(merged_stats.get(candidate), dict) else {}
                    if cand_bucket.get("can_do") is True:
                        return {
                            **decision,
                            "action": candidate,
                            "reasoning": f"系统拦截：{action} 配额不可用，改为 {candidate}",
                            "params": {},
                        }
                return {
                    **decision,
                    "action": "query_stats",
                    "reasoning": "系统拦截：当前动作配额不可用，重新同步配额",
                    "params": {"platform": brief.platform},
                }
        return decision

    return decision
