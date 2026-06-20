from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.platforms.types import normalize_platform
from app.services.interaction_log_service import InteractionLogService


def build_task_ledger(
    *,
    job_id: str,
    settings: Settings,
    tenant_id: str,
    platform: str,
    account_id: str,
    db_session: Session | None,
    memory_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 job_id 汇总任务级台账（互动次数、评论/关注/私信状态）。

    约定：Supervisor Job 执行触达时，interaction_logs.task_id = job_id。
    全局日配额仍走 query_stats（account + today）；本台账仅统计本任务贡献。
    """
    ledger: dict[str, Any] = {
        "job_id": job_id,
        "source": "database",
        "stats": {
            "reply": {"ok": 0, "failed": 0},
            "follow": {"ok": 0, "failed": 0},
            "dm": {"ok": 0, "failed": 0},
        },
        "total_outreach_ok": 0,
        "recent_actions": [],
        "comment_status": [],
        "user_status": [],
    }

    if memory_ledger and isinstance(memory_ledger, dict):
        ledger["source"] = "memory"
        ledger["stats"] = memory_ledger.get("stats") or ledger["stats"]
        ledger["total_outreach_ok"] = int(memory_ledger.get("total_outreach_ok") or 0)
        ledger["recent_actions"] = memory_ledger.get("recent_actions") or []
        ledger["comment_status"] = memory_ledger.get("comment_status") or []
        ledger["user_status"] = memory_ledger.get("user_status") or []
        return ledger

    if db_session is None or not job_id:
        ledger["source"] = "unavailable"
        return ledger

    service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
    platform_norm = normalize_platform(platform)
    data = service.query_task_ledger(
        job_id=job_id,
        platform=platform_norm,
        account_id=account_id or "default",
    )
    ledger.update(data)
    ledger["job_id"] = job_id
    return ledger


def append_memory_ledger_action(
    state: dict[str, Any],
    *,
    action: str,
    ok: bool,
    summary: str = "",
    comment_id: str | None = None,
    target_user_id: str | None = None,
    target_nickname: str | None = None,
    reply_text: str | None = None,
) -> None:
    """dry_run 时在内存维护任务台账。"""
    ledger = state.get("task_ledger")
    if not isinstance(ledger, dict):
        ledger = {
            "stats": {"reply": {"ok": 0, "failed": 0}, "follow": {"ok": 0, "failed": 0}, "dm": {"ok": 0, "failed": 0}},
            "total_outreach_ok": 0,
            "recent_actions": [],
            "comment_status": [],
            "user_status": [],
        }
    stats = ledger.setdefault("stats", {})
    bucket = stats.setdefault(action, {"ok": 0, "failed": 0})
    if action in {"reply", "follow", "dm"}:
        key = "ok" if ok else "failed"
        bucket[key] = int(bucket.get(key) or 0) + 1
        if ok:
            ledger["total_outreach_ok"] = int(ledger.get("total_outreach_ok") or 0) + 1

    entry = {
        "action": action,
        "status": "ok" if ok else "failed",
        "summary": summary,
        "comment_id": comment_id,
        "target_user_id": target_user_id,
        "target_nickname": target_nickname,
    }
    recent = ledger.setdefault("recent_actions", [])
    recent.append(entry)
    ledger["recent_actions"] = recent[-50:]

    if action == "reply" and comment_id:
        comments = ledger.setdefault("comment_status", [])
        comments.append(
            {
                "comment_id": comment_id,
                "status": "ok" if ok else "failed",
                "reply_text": reply_text or "",
                "action": "reply",
            }
        )
        ledger["comment_status"] = comments[-100:]

    if action in {"follow", "dm"} and (target_user_id or target_nickname):
        users = ledger.setdefault("user_status", [])
        users.append(
            {
                "target_user_id": target_user_id,
                "target_nickname": target_nickname,
                "status": "ok" if ok else "failed",
                "action": action,
            }
        )
        ledger["user_status"] = users[-100:]

    state["task_ledger"] = ledger
