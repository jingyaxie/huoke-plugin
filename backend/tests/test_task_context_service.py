from __future__ import annotations

from app.services.task_brief_service import TaskBrief
from app.services.task_context_service import build_job_execution_stats


def _brief() -> TaskBrief:
    return TaskBrief(
        keyword="团餐",
        platform="douyin",
        region="",
        goals={"target_leads": 10, "crawl_video_limit": 4},
        constraints={"daily_reply_limit": 20},
        success_criteria="",
        brief_md="",
        allowed_skills=[],
    )


def test_build_job_execution_stats_aggregates_crawl_and_outreach() -> None:
    job_result = {
        "supervisor_state": {
            "comments_captured": 12,
            "comments_persisted": 8,
            "leads_collected": 3,
            "crawl_done": True,
            "videos_processed": 4,
            "crawl_search_exhausted": True,
        },
        "supervisor_cycles": [
            {"action": "crawl_keyword", "ok": True},
            {"action": "crawl_keyword", "ok": False},
            {"action": "reply", "ok": True},
        ],
    }
    progress = {
        "comments_captured": 12,
        "leads_collected": 3,
        "target_leads": 10,
        "crawl_done": True,
        "pct": 30.0,
    }
    task_ledger = {
        "stats": {
            "reply": {"ok": 2, "failed": 1},
            "dm": {"ok": 1, "failed": 0},
            "follow": {"ok": 0, "failed": 1},
        },
        "total_outreach_ok": 3,
        "comment_status": [
            {"comment_id": "c1", "status": "ok"},
            {"comment_id": "c2", "status": "failed"},
        ],
    }
    interaction_stats = {
        "reply": {"count": 5, "limit": 20, "remaining": 15},
    }

    stats = build_job_execution_stats(
        brief=_brief(),
        job_result=job_result,
        progress=progress,
        task_ledger=task_ledger,
        interaction_stats=interaction_stats,
        sandbox_stats={"outreach_ok": 3},
    )

    assert stats["comments_captured"] == 12
    assert stats["comments_persisted"] == 8
    assert stats["comments_replied"] == 1
    assert stats["crawl_video_limit"] == 4
    assert stats["videos_processed"] == 4
    assert stats["crawl_search_exhausted"] is True
    assert stats["crawl_success_count"] == 1
    assert stats["crawl_fail_count"] == 1
    assert stats["crawl_done"] is True
    assert stats["reply"]["ok"] == 2
    assert stats["reply"]["failed"] == 1
    assert stats["reply"]["daily"]["used"] == 5
    assert stats["total_outreach_ok"] == 3
    assert stats["progress_pct"] == 30.0


def test_build_job_execution_stats_includes_round_loop() -> None:
    brief = TaskBrief(
        keyword="团餐",
        platform="douyin",
        goals={"target_leads": 80, "repeat_mode": "round", "round_target_count": 80, "max_rounds": 2},
        constraints={"repeat_mode": "round", "round_target_count": 80, "max_rounds": 2},
    )
    stats = build_job_execution_stats(
        brief=brief,
        job_result={
            "supervisor_state": {
                "round_index": 2,
                "round_leads_collected": 30,
                "round_target_leads": 80,
                "total_leads_collected": 110,
                "rounds": [{"round": 1, "status": "completed", "leads_collected": 80}],
            }
        },
        progress={"leads_collected": 30, "target_leads": 80},
        task_ledger={},
        interaction_stats={},
    )
    assert stats["round"]["round_index"] == 2
    assert stats["round"]["round_leads_collected"] == 30
    assert stats["round"]["total_leads_collected"] == 110
