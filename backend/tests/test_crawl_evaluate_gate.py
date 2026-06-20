from __future__ import annotations

from app.services.supervisor_action_guard import guard_supervisor_action
from app.services.supervisor_crawl_helpers import (
    crawl_evaluate_gate,
    crawl_evaluate_thresholds,
    record_crawl_round_without_evaluation,
    reset_crawl_evaluate_gate_state,
    should_resume_crawl_on_no_match,
)
from app.services.task_brief_service import TaskBrief


def _skill_flow_brief(**goals) -> TaskBrief:
    return TaskBrief(
        keyword="健身房",
        platform="douyin",
        goals={
            "target_leads": 5,
            "execution_mode": "skill_flow",
            "agent_strategy": "skill-flow-douyin",
            **goals,
        },
    )


def test_thresholds_scale_with_target_and_video_limit():
    brief = _skill_flow_brief(crawl_video_limit=5)
    thresholds = crawl_evaluate_thresholds(brief)
    assert thresholds["min_comments_before_evaluate"] >= 50
    assert thresholds["max_crawl_rounds_before_evaluate"] == 3
    assert thresholds["max_comments_hard_cap"] >= 500


def test_force_evaluate_when_inventory_reaches_min():
    brief = _skill_flow_brief(min_comments_before_evaluate=100)
    gate = crawl_evaluate_gate(brief, {"comments_captured": 120})
    assert gate.force_evaluate is True
    assert gate.suspend is False
    assert "LLM 评估" in gate.reason


def test_force_evaluate_after_max_rounds_with_inventory():
    brief = _skill_flow_brief(max_crawl_rounds_before_evaluate=2)
    gate = crawl_evaluate_gate(brief, {"crawl_rounds_without_eval": 2, "comments_persisted": 10})
    assert gate.force_evaluate is True


def test_suspend_when_hard_cap_exceeded():
    brief = _skill_flow_brief(max_comments_captured=200)
    gate = crawl_evaluate_gate(brief, {"comments_captured": 250})
    assert gate.suspend is True
    assert gate.completion_outcome == "crawl_inventory_cap"


def test_suspend_when_max_rounds_without_inventory():
    brief = _skill_flow_brief(max_crawl_rounds_before_evaluate=2)
    gate = crawl_evaluate_gate(brief, {"crawl_rounds_without_eval": 2})
    assert gate.suspend is True
    assert gate.completion_outcome == "crawl_no_inventory"


def test_gate_inactive_after_evaluation():
    brief = _skill_flow_brief()
    gate = crawl_evaluate_gate(brief, {"comments_captured": 9999, "evaluation_done": True})
    assert gate.force_evaluate is False
    assert gate.suspend is False


def test_record_and_reset_crawl_rounds():
    state: dict = {}
    record_crawl_round_without_evaluation(state)
    record_crawl_round_without_evaluation(state)
    assert state["crawl_rounds_without_eval"] == 2
    state["evaluation_done"] = True
    record_crawl_round_without_evaluation(state)
    assert state["crawl_rounds_without_eval"] == 2
    reset_crawl_evaluate_gate_state(state)
    assert "crawl_rounds_without_eval" not in state


def test_should_not_resume_crawl_when_gate_forces_evaluate():
    brief = _skill_flow_brief(min_comments_before_evaluate=50)
    state = {"comments_captured": 80}
    assert should_resume_crawl_on_no_match(brief, state) is False


def test_should_not_resume_crawl_for_account_home_manual():
    brief = TaskBrief(
        keyword="",
        platform="douyin",
        goals={
            "target_leads": 50,
            "execution_mode": "skill_flow",
            "acquisition_mode": "account_home",
            "profile_url": "https://www.douyin.com/user/test",
        },
    )
    state = {"evaluation_done": True, "leads_qualified": 0}
    assert should_resume_crawl_on_no_match(brief, state) is False


def test_guard_blocks_crawl_when_inventory_high():
    brief = _skill_flow_brief(min_comments_before_evaluate=50)
    decision = guard_supervisor_action(
        {"action": "crawl_keyword", "params": {"keyword": "健身房"}},
        brief=brief,
        state={"comments_captured": 100},
    )
    assert decision["action"] == "evaluate_leads"
