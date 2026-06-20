from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.platforms.types import normalize_platform
from app.services.interaction_log_service import InteractionLogService
from app.services.task_brief_service import TaskBrief
from app.services.supervisor_crawl_helpers import effective_crawl_video_limit
from app.services.task_round_service import (
    effective_leads_collected,
    effective_live_leads_qualified,
    effective_target_leads,
    max_rounds_from_brief,
    round_loop_enabled,
)
from app.services.task_job_ledger_service import build_task_ledger
from app.services.task_sandbox_runtime import TaskSandboxRuntime


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outreach_bucket(stats: dict[str, Any], key: str) -> dict[str, int]:
    bucket = stats.get(key) if isinstance(stats.get(key), dict) else {}
    return {
        "ok": int(bucket.get("ok") or 0),
        "failed": int(bucket.get("failed") or 0),
    }


def _daily_quota(interaction_stats: dict[str, Any], key: str) -> dict[str, Any]:
    row = interaction_stats.get(key) if isinstance(interaction_stats.get(key), dict) else {}
    return {
        "used": int(row.get("count") or 0),
        "limit": row.get("limit"),
        "remaining": row.get("remaining"),
    }


def build_job_execution_stats(
    *,
    brief: TaskBrief,
    job_result: dict[str, Any],
    progress: dict[str, Any],
    task_ledger: dict[str, Any],
    interaction_stats: dict[str, Any],
    sandbox_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """汇总任务执行统计，供详情页与 Supervisor 决策展示。"""
    supervisor_state = job_result.get("supervisor_state")
    if not isinstance(supervisor_state, dict):
        supervisor_state = {}

    cycles = job_result.get("supervisor_cycles")
    crawl_ok = crawl_fail = 0
    if isinstance(cycles, list):
        for cycle in cycles:
            if not isinstance(cycle, dict):
                continue
            if str(cycle.get("action") or "") != "crawl_keyword":
                continue
            if cycle.get("ok"):
                crawl_ok += 1
            else:
                crawl_fail += 1

    stats = task_ledger.get("stats") if isinstance(task_ledger.get("stats"), dict) else {}
    reply = _outreach_bucket(stats, "reply")
    dm = _outreach_bucket(stats, "dm")
    follow = _outreach_bucket(stats, "follow")

    comments_captured = int(
        progress.get("comments_captured") or supervisor_state.get("comments_captured") or 0
    )
    crawl_video_limit = effective_crawl_video_limit(brief=brief)
    videos_processed = int(supervisor_state.get("videos_processed") or 0)
    comments_persisted = int(supervisor_state.get("comments_persisted") or 0)
    target_leads = int(progress.get("target_leads") or effective_target_leads(brief, supervisor_state) or 0)
    leads_collected = int(progress.get("leads_collected") or effective_leads_collected(brief, supervisor_state) or 0)
    progress_pct = progress.get("pct")
    if progress_pct is None and target_leads:
        progress_pct = round(100 * leads_collected / target_leads, 1)
    else:
        progress_pct = float(progress_pct or 0)

    comment_status = task_ledger.get("comment_status")
    comments_replied = 0
    if isinstance(comment_status, list):
        comments_replied = sum(
            1 for row in comment_status if isinstance(row, dict) and row.get("status") == "ok"
        )

    sandbox = sandbox_stats if isinstance(sandbox_stats, dict) else {}

    result = {
        "comments_captured": comments_captured,
        "comments_persisted": comments_persisted,
        "comments_replied": comments_replied,
        "crawl_video_limit": crawl_video_limit,
        "videos_processed": videos_processed,
        "crawl_search_exhausted": bool(supervisor_state.get("crawl_search_exhausted")),
        "crawl_done": bool(progress.get("crawl_done") or supervisor_state.get("crawl_done")),
        "crawl_success_count": crawl_ok,
        "crawl_fail_count": crawl_fail,
        "target_leads": target_leads,
        "leads_collected": leads_collected,
        "progress_pct": progress_pct,
        "reply": {**reply, "daily": _daily_quota(interaction_stats, "reply")},
        "dm": {**dm, "daily": _daily_quota(interaction_stats, "dm")},
        "follow": {**follow, "daily": _daily_quota(interaction_stats, "follow")},
        "total_outreach_ok": int(
            task_ledger.get("total_outreach_ok") or reply["ok"] + dm["ok"] + follow["ok"]
        ),
        "sandbox_outreach_ok": int(sandbox.get("outreach_ok") or 0),
    }
    if round_loop_enabled(brief):
        result["round"] = {
            "mode": "round",
            "round_index": int(supervisor_state.get("round_index") or 1),
            "max_rounds": max_rounds_from_brief(brief),
            "round_leads_collected": effective_leads_collected(brief, supervisor_state),
            "round_target_leads": effective_target_leads(brief, supervisor_state),
            "total_leads_collected": int(supervisor_state.get("total_leads_collected") or 0),
            "completed_rounds": supervisor_state.get("rounds") if isinstance(supervisor_state.get("rounds"), list) else [],
        }
    return result


def build_data_snapshot(
    *,
    brief: TaskBrief,
    job_result: dict[str, Any],
    settings: Settings,
    tenant_id: str,
    platform: str,
    account_id: str,
    db_session: Session | None,
    job_id: str = "",
) -> dict[str, Any]:
    """汇总 Supervisor 决策所需的数据快照。"""
    supervisor_state = job_result.get("supervisor_state")
    if not isinstance(supervisor_state, dict):
        supervisor_state = {}

    cycles = job_result.get("supervisor_cycles")
    cycle_count = len(cycles) if isinstance(cycles, list) else 0

    interaction_stats: dict[str, Any] = {}
    sim = supervisor_state.get("simulated_stats")
    if isinstance(sim, dict):
        interaction_stats = sim
    elif db_session is not None:
        log_service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
        platform_norm = normalize_platform(platform)
        reply_limit = brief.constraints.get("daily_reply_limit")
        follow_limit = brief.constraints.get("daily_follow_limit")
        dm_limit = brief.constraints.get("daily_dm_limit")
        interaction_stats = log_service.query_stats(
            platform=platform_norm,
            account_id=account_id or "default",
            period="today",
            reply_limit=int(reply_limit) if reply_limit is not None else None,
            follow_limit=int(follow_limit) if follow_limit is not None else None,
            dm_limit=int(dm_limit) if dm_limit is not None else None,
        )

    leads_collected = effective_leads_collected(brief, supervisor_state)
    crawl_done = bool(supervisor_state.get("crawl_done"))
    last_action = supervisor_state.get("last_action")
    target_leads = effective_target_leads(brief, supervisor_state) or int(brief.goals.get("target_leads") or 50)
    crawl_video_limit = effective_crawl_video_limit(brief=brief)

    task_ledger = build_task_ledger(
        job_id=job_id or str(job_result.get("job_id") or ""),
        settings=settings,
        tenant_id=tenant_id,
        platform=platform,
        account_id=account_id,
        db_session=db_session,
        memory_ledger=supervisor_state.get("task_ledger") if isinstance(supervisor_state.get("task_ledger"), dict) else None,
    )

    sandbox_stats: dict[str, Any] = {"available": False}
    effective_job_id = job_id or str(job_result.get("job_id") or "")
    if effective_job_id:
        runtime = TaskSandboxRuntime(settings, tenant_id, effective_job_id)
        if runtime.available:
            sandbox_stats = runtime.get_summary()
            outreach_ok = int(sandbox_stats.get("outreach_ok") or 0)
            if outreach_ok > 0:
                leads_collected = max(leads_collected, outreach_ok)
            if int(sandbox_stats.get("crawl_comments_total") or 0) > 0:
                crawl_done = True

    progress = {
        "leads_collected": leads_collected,
        "leads_qualified": effective_live_leads_qualified(supervisor_state, job_result=job_result),
        "comments_captured": int(supervisor_state.get("comments_captured") or 0),
        "crawl_video_limit": crawl_video_limit,
        "videos_processed": int(supervisor_state.get("videos_processed") or 0),
        "crawl_search_exhausted": bool(supervisor_state.get("crawl_search_exhausted")),
        "target_leads": target_leads,
        "crawl_done": crawl_done,
        "stats_synced": bool(supervisor_state.get("stats_synced")),
        "last_action": last_action,
        "pct": round(100 * leads_collected / target_leads, 1) if target_leads else 0,
    }
    if round_loop_enabled(brief):
        progress.update(
            {
                "repeat_mode": "round",
                "round_index": int(supervisor_state.get("round_index") or 1),
                "max_rounds": max_rounds_from_brief(brief),
                "round_leads_collected": leads_collected,
                "round_target_leads": target_leads,
                "total_leads_collected": int(supervisor_state.get("total_leads_collected") or 0),
                "completed_rounds": supervisor_state.get("rounds") if isinstance(supervisor_state.get("rounds"), list) else [],
            }
        )
    execution_stats = build_job_execution_stats(
        brief=brief,
        job_result=job_result,
        progress=progress,
        task_ledger=task_ledger,
        interaction_stats=interaction_stats,
        sandbox_stats=sandbox_stats,
    )

    return {
        "at": _utc_now_iso(),
        "cycle": cycle_count,
        "platform": platform,
        "account_id": account_id,
        "goals": brief.goals,
        "constraints": brief.constraints,
        "progress": progress,
        "interaction_stats": interaction_stats,
        "task_ledger": task_ledger,
        "sandbox_stats": sandbox_stats,
        "execution_stats": execution_stats,
        "recent_cycles": (cycles[-3:] if isinstance(cycles, list) else []),
    }
