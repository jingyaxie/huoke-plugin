from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.task_brief_service import TaskBrief


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def round_mode_from_brief(brief: TaskBrief) -> str:
    raw = brief.constraints.get("repeat_mode")
    if raw is None:
        raw = brief.goals.get("repeat_mode")
    mode = str(raw or "").strip().lower()
    if mode in {"round", "rounds", "cycle", "loop"}:
        return "round"
    return "none"


def round_loop_enabled(brief: TaskBrief) -> bool:
    return round_mode_from_brief(brief) == "round"


def max_rounds_from_brief(brief: TaskBrief) -> int:
    for src in (brief.constraints, brief.goals):
        val = src.get("max_rounds") if isinstance(src, dict) else None
        if val is None:
            continue
        try:
            return max(1, int(val))
        except (TypeError, ValueError):
            continue
    return 1


def round_target_from_brief(brief: TaskBrief) -> int:
    for src in (brief.constraints, brief.goals):
        if not isinstance(src, dict):
            continue
        for key in ("round_target_count", "round_target_leads", "target_leads", "target_count"):
            val = src.get(key)
            if val is None:
                continue
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            if n > 0:
                return n
    return int(brief.goals.get("target_leads") or 0)


def current_round_index(state: dict[str, Any]) -> int:
    return max(1, int(state.get("round_index") or 1))


def current_round_leads(state: dict[str, Any]) -> int:
    if state.get("round_leads_collected") is not None:
        return int(state.get("round_leads_collected") or 0)
    return int(state.get("leads_collected") or 0)


def ensure_round_state(brief: TaskBrief, state: dict[str, Any]) -> None:
    if not round_loop_enabled(brief):
        return
    state["repeat_mode"] = "round"
    state["round_index"] = current_round_index(state)
    state["round_target_leads"] = round_target_from_brief(brief)
    state.setdefault("round_leads_collected", int(state.get("leads_collected") or 0))
    state.setdefault("total_leads_collected", int(state.get("leads_collected") or 0))
    state.setdefault("rounds", [])


def effective_target_leads(brief: TaskBrief, state: dict[str, Any]) -> int:
    if round_loop_enabled(brief):
        ensure_round_state(brief, state)
        return int(state.get("round_target_leads") or round_target_from_brief(brief) or 0)
    return int(brief.goals.get("target_leads") or 0)


def effective_leads_collected(brief: TaskBrief, state: dict[str, Any]) -> int:
    if round_loop_enabled(brief):
        ensure_round_state(brief, state)
        return current_round_leads(state)
    return int(state.get("leads_collected") or 0)


def effective_leads_qualified(state: dict[str, Any]) -> int:
    return int(state.get("leads_qualified") or 0)


def persisted_precise_comment_count(state: dict[str, Any]) -> int:
    """standalone 入库清单：精准 comment_id 数以 job_persisted_comment_ids 为准。"""
    raw = state.get("job_persisted_comment_ids")
    if not isinstance(raw, list):
        return 0
    return len({str(x).strip() for x in raw if str(x).strip()})


def standalone_outreach_incomplete(brief: TaskBrief, state: dict[str, Any]) -> bool:
    """一体化浏览：精准线索已够，但成功触达数未达目标。"""
    from app.services.standalone_browse_adapter import is_standalone_browse_brief

    if not is_standalone_browse_brief(brief):
        return False
    if bool(brief.goals.get("outreach_validate_only")):
        return False
    target = int(brief.goals.get("target_leads") or 0)
    if target <= 0:
        return False
    if effective_leads_qualified(state) < target:
        return False
    return effective_leads_collected(brief, state) < target


def historical_qualified_peak_from_progress(job_result: dict[str, Any] | None) -> int:
    """从 progress_events 取历史峰值（任务中断后未写入 state 时用于恢复展示）。"""
    if not isinstance(job_result, dict):
        return 0
    events = job_result.get("progress_events")
    if not isinstance(events, list):
        return 0
    best = 0
    for ev in events:
        if not isinstance(ev, dict) or ev.get("type") != "crawl_progress":
            continue
        data = ev.get("data")
        if isinstance(data, dict):
            best = max(best, int(data.get("leads_qualified") or 0))
    return best


def effective_live_leads_qualified(
    state: dict[str, Any],
    *,
    job_result: dict[str, Any] | None = None,
) -> int:
    """任务进行中：优先已入库精准清单，其次 state / crawl_live（均为累计值，勿重复相加）。"""
    persisted = persisted_precise_comment_count(state)
    if persisted > 0:
        return persisted
    committed = effective_leads_qualified(state)
    historical = historical_qualified_peak_from_progress(job_result)
    crawl_live = state.get("crawl_live")
    session_q = 0
    if isinstance(crawl_live, dict):
        session_q = int(crawl_live.get("leads_qualified") or 0)
    return max(committed, historical, session_q)


def uses_qualified_leads_goal(brief: TaskBrief) -> bool:
    """standalone 一体化浏览：目标为精准线索数（leads_qualified），可超过 target。"""
    from app.services.standalone_browse_adapter import is_standalone_browse_brief

    if is_standalone_browse_brief(brief):
        return True
    if str(brief.goals.get("goal_metric") or "").strip().lower() == "leads_qualified":
        return True
    return False


def effective_supervisor_goal_count(brief: TaskBrief, state: dict[str, Any]) -> int:
    if uses_qualified_leads_goal(brief):
        return effective_leads_qualified(state)
    return effective_leads_collected(brief, state)


def goal_reached_for_current_round(brief: TaskBrief, state: dict[str, Any]) -> bool:
    target = effective_target_leads(brief, state)
    if target <= 0:
        return False
    return effective_leads_collected(brief, state) >= target


def _reset_round_work_state(state: dict[str, Any]) -> None:
    for key in (
        "crawl_done",
        "visible_crawl_done",
        "stats_synced",
        "last_stats",
        "last_action",
        "last_crawl_error",
        "crawl_search_exhausted",
        "outreach_quota_exhausted",
        "completion_outcome",
        "comments_captured",
        "comments_persisted",
        "raw_comments_scanned",
        "videos_processed",
        "watched_content_ids",
        "url_revisited_content_ids",
    ):
        state.pop(key, None)
    state["stale_cycles"] = 0
    state["_repeat_action_count"] = 0
    state.pop("_repeat_action", None)


def complete_current_round(brief: TaskBrief, state: dict[str, Any]) -> dict[str, Any]:
    ensure_round_state(brief, state)
    round_index = current_round_index(state)
    target = int(state.get("round_target_leads") or round_target_from_brief(brief) or 0)
    leads = current_round_leads(state)
    rounds = state.get("rounds")
    if not isinstance(rounds, list):
        rounds = []
    rounds.append(
        {
            "round": round_index,
            "status": "completed",
            "leads_collected": leads,
            "target_leads": target,
            "completed_at": _utc_now_iso(),
        }
    )
    state["rounds"] = rounds[-100:]
    state["total_leads_collected"] = int(state.get("total_leads_collected") or 0) + leads
    return {"round": round_index, "leads_collected": leads, "target_leads": target}


def start_next_round(brief: TaskBrief, state: dict[str, Any]) -> bool:
    if not round_loop_enabled(brief):
        return False
    ensure_round_state(brief, state)
    if current_round_index(state) >= max_rounds_from_brief(brief):
        return False
    next_round = current_round_index(state) + 1
    _reset_round_work_state(state)
    state["repeat_mode"] = "round"
    state["round_index"] = next_round
    state["round_target_leads"] = round_target_from_brief(brief)
    state["round_leads_collected"] = 0
    state["leads_collected"] = 0
    return True
