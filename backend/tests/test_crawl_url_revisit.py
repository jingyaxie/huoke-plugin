from __future__ import annotations

from app.services.supervisor_crawl_helpers import (
    build_url_revisit_decision,
    content_id_to_video_url,
    mark_url_revisited,
    pending_url_revisit_content_ids,
    pick_next_url_revisit_target,
)
from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import build_supervisor_execution_plan, plan_driven_supervisor_decision


def _skill_flow_brief() -> TaskBrief:
    return TaskBrief(
        keyword="健身房",
        region="北京",
        platform="douyin",
        goals={
            "target_leads": 5,
            "comment_days": 7,
            "execution_mode": "skill_flow",
            "ui_first": True,
        },
    )


def test_content_id_to_video_url_douyin():
    assert content_id_to_video_url("douyin", "123") == "https://www.douyin.com/video/123"


def test_pick_next_url_revisit_target_skips_revisited():
    brief = _skill_flow_brief()
    state = {
        "watched_content_ids": ["111", "222"],
        "url_revisited_content_ids": ["111"],
    }
    target = pick_next_url_revisit_target(brief, state)
    assert target == {"content_id": "222", "video_url": "https://www.douyin.com/video/222"}
    assert pending_url_revisit_content_ids(state) == ["222"]


def test_plan_prefers_url_revisit_over_repeat_search():
    brief = _skill_flow_brief()
    plan = build_supervisor_execution_plan(brief, {})
    state = {
        "watched_content_ids": ["7297943541437779236"],
        "comments_captured": 0,
    }
    decision = plan_driven_supervisor_decision(plan, brief, state)
    assert decision is not None
    assert decision["action"] == "crawl_content_url"
    assert decision["params"]["video_url"] == "https://www.douyin.com/video/7297943541437779236"
    assert decision["params"]["_revisit_under_crawl_step"] is True


def test_plan_failed_crawl_keyword_falls_back_to_url_revisit():
    brief = _skill_flow_brief()
    plan = build_supervisor_execution_plan(brief, {})
    plan["steps"][0]["status"] = "failed"
    state = {
        "watched_content_ids": ["7546195030865956156"],
    }
    decision = plan_driven_supervisor_decision(plan, brief, state)
    assert decision is not None
    assert decision["action"] == "crawl_content_url"
    assert plan["steps"][0]["status"] == "in_progress"


def test_mark_url_revisited_tracks_attempts():
    state: dict = {"watched_content_ids": ["111", "222"]}
    mark_url_revisited(state, "111")
    assert state["url_revisited_content_ids"] == ["111"]
    assert build_url_revisit_decision(
        _skill_flow_brief(),
        state,
        reasoning="补抓",
    )["params"]["_revisit_content_id"] == "222"
