from __future__ import annotations

from app.services.task_brief_service import TaskBrief
from app.services.task_execution_plan import (
    advance_supervisor_plan,
    build_execution_note,
    build_supervisor_execution_plan,
    guard_supervisor_complete_decision,
    infer_suspend_next_action,
    plan_driven_supervisor_decision,
    reset_supervisor_state_for_manual_retry,
    supervisor_goal_reached,
)


def test_reset_supervisor_state_for_manual_retry_after_crawl_failed():
    brief = TaskBrief(keyword="团餐配送", goals={"target_leads": 10, "video_limit": 1}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {"crawl_failures": 1})
    plan["steps"][0]["status"] = "failed"
    state = {
        "suspended": True,
        "resume_at": "2099-01-01T00:00:00+00:00",
        "wake_reason": "抓取失败",
        "crawl_failures": 1,
        "execution_plan": plan,
    }
    reset_supervisor_state_for_manual_retry(state, plan)
    assert not state.get("suspended")
    assert state.get("crawl_failures") == 0
    assert state.get("crawl_done") is None
    assert plan["steps"][0]["status"] == "pending"
    decision = plan_driven_supervisor_decision(plan, brief, state)
    assert decision is not None
    assert decision.get("action") == "crawl_keyword"
    brief2 = TaskBrief(keyword="团餐配送", goals={"target_leads": 10, "video_limit": 1}, platform="douyin")
    plan2 = build_supervisor_execution_plan(brief2, {})
    actions = [s["action"] for s in plan2["steps"]]
    assert actions == ["crawl_keyword", "query_stats", "complete"]
    assert plan2["current_index"] == 0


def test_reset_manual_retry_after_crawl_profile_failed_skill_flow_brief():
    """手动获客主页任务（skill_flow brief）抓取失败后，继续执行应回到 crawl_profile。"""
    brief = TaskBrief(
        keyword="",
        platform="douyin",
        goals={
            "target_leads": 50,
            "comment_days": 3,
            "execution_mode": "skill_flow",
            "acquisition_mode": "account_home",
            "profile_url": "https://www.douyin.com/user/test",
            "crawl_video_limit": 10,
        },
        agent_strategy="douyin_supervisor",
    )
    plan = build_supervisor_execution_plan(brief, {})
    plan["steps"][0]["status"] = "failed"
    state = {
        "suspended": True,
        "wake_reason": "抓取失败",
        "execution_plan": plan,
    }
    reset_supervisor_state_for_manual_retry(state, plan, brief=brief)
    assert plan["steps"][0]["action"] == "crawl_profile"
    assert plan["steps"][0]["status"] == "pending"
    decision = plan_driven_supervisor_decision(plan, brief, state)
    assert decision is not None
    assert decision.get("action") == "crawl_profile"


def test_manual_resume_after_crawl_profile_failed_resets_evaluate_step():
    brief = TaskBrief(
        title="博主-test",
        goals={
            "target_leads": 50,
            "comment_days": 3,
            "execution_mode": "skill_flow",
            "acquisition_mode": "account_home",
            "profile_url": "https://www.douyin.com/user/test",
            "crawl_video_limit": 10,
            "supervisor_plan_only": True,
        },
        agent_strategy="skill-flow-douyin",
        platform="douyin",
    )
    plan = build_supervisor_execution_plan(brief, {"evaluation_done": True})
    for step in plan["steps"]:
        if step.get("action") == "evaluate_leads":
            assert step["status"] == "completed"
    state = {
        "suspended": True,
        "wake_reason": "0 条评论",
        "execution_plan": plan,
        "crawl_done": True,
        "evaluation_done": True,
        "leads_qualified": 0,
        "stats_synced": True,
    }

    reset_supervisor_state_for_manual_retry(state, plan, brief=brief)
    assert state.get("evaluation_done") is None
    eval_step = next(s for s in plan["steps"] if s.get("action") == "evaluate_leads")
    assert eval_step["status"] == "pending"

    decision = plan_driven_supervisor_decision(plan, brief, state)
    assert decision is not None
    assert decision.get("action") == "crawl_profile"


def test_manual_source_exhausted_suspend_next_action():
    brief = TaskBrief(
        title="博主-test",
        goals={
            "target_leads": 50,
            "acquisition_mode": "account_home",
            "profile_url": "https://www.douyin.com/user/test",
        },
        platform="douyin",
    )
    state = {
        "completion_outcome": "source_exhausted",
        "crawl_search_exhausted": True,
        "crawl_done": True,
    }
    next_action = infer_suspend_next_action("主页 0 条评论", state, brief)
    assert "关键词" not in next_action
    assert "评论时间窗" in next_action or "采集几天内评论" in next_action


def test_manual_source_exhausted_execution_note():
    brief = {
        "title": "博主-test",
        "goals": {"acquisition_mode": "account_home", "target_leads": 50},
        "platform": "douyin",
    }
    note = build_execution_note(
        job_status="suspended",
        job_stage="track",
        job_result={
            "completion_outcome": "source_exhausted",
            "supervisor_state": {"suspended": True, "leads_collected": 0},
            "data_snapshot": {"progress": {"leads_collected": 0, "target_leads": 50}},
            "orchestration": {"task_brief": brief},
        },
    )
    assert note is not None
    assert "关键词" not in note
    assert "评论时间窗" in note


def test_plan_driven_decide_starts_with_crawl():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {})
    decision = plan_driven_supervisor_decision(plan, brief, {})
    assert decision is not None
    assert decision["action"] == "crawl_keyword"
    assert decision.get("plan_step_id") == "crawl"
    assert decision["params"]["crawl_video_limit"] == 5
    assert decision["params"]["video_limit"] == 5


def test_plan_driven_skips_completed_crawl():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True})
    decision = plan_driven_supervisor_decision(plan, brief, {"crawl_done": True})
    assert decision is not None
    assert decision["action"] == "query_stats"


def test_skill_flow_plan_includes_reply_loop():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 10, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        platform="douyin",
    )
    plan = build_supervisor_execution_plan(brief, {})
    actions = [s["action"] for s in plan["steps"]]
    assert actions == ["crawl_keyword", "evaluate_leads", "query_stats", "reply", "dm", "follow", "complete"]
    crawl_params = plan["steps"][0]["params"]
    assert crawl_params["ui_search_only"] is True
    assert crawl_params["search_url_first"] is False
    assert crawl_params["crawl_video_limit"] == 5
    assert plan["steps"][3]["repeat_until"] == "quota_or_no_targets"
    assert plan.get("pipeline") == "skill_flow"


def test_plan_uses_crawl_video_limit_alias():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5, "crawl_video_limit": 9}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {})
    crawl_params = plan["steps"][0]["params"]
    assert crawl_params["crawl_video_limit"] == 9
    assert crawl_params["video_limit"] == 9
    assert "最多 9 个视频" in plan["steps"][0]["label"]


def test_skill_flow_plan_driven_reply_after_stats():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        platform="douyin",
    )
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True, "evaluation_done": True, "stats_synced": True})
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        {"crawl_done": True, "evaluation_done": True, "stats_synced": True},
        stats={"reply": {"can_do": True}},
    )
    assert decision is not None
    assert decision["action"] == "reply"
    assert decision.get("plan_step_id") == "reply"


def test_skill_flow_plan_recrawls_when_zero_qualified_leads():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        platform="douyin",
    )
    state = {
        "crawl_done": True,
        "evaluation_done": True,
        "leads_qualified": 0,
        "stats_synced": True,
        "comments_captured": 26,
        "watched_content_ids": ["v1"],
    }
    plan = build_supervisor_execution_plan(brief, state)
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        state,
        stats={"reply": {"can_do": True}},
    )
    assert decision is not None
    assert decision["action"] == "crawl_keyword"
    assert state.get("crawl_done") is None
    assert state.get("evaluation_done") is None


def test_skill_flow_next_day_resume_restarts_with_crawl():
    from datetime import datetime, timedelta, timezone

    from app.services.task_supervisor_service import TaskSupervisorService

    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
        constraints={"termination_resume_next_day": True},
        platform="douyin",
    )
    plan = build_supervisor_execution_plan(
        brief,
        {"crawl_done": True, "stats_synced": True},
    )
    state = {
        "suspended": True,
        "resume_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "day_index": 1,
        "crawl_done": True,
        "stats_synced": True,
        "last_stats": {"reply": {"can_do": True}},
        "execution_plan": plan,
    }
    TaskSupervisorService._maybe_wake_suspended_state(object.__new__(TaskSupervisorService), state, brief)
    assert state.get("suspended") is False
    assert state.get("day_index") == 2
    assert state.get("crawl_done") is None
    assert state.get("stats_synced") is None
    assert state["execution_plan"]["current_index"] == 0
    decision = plan_driven_supervisor_decision(state["execution_plan"], brief, state)
    assert decision is not None
    assert decision["action"] == "crawl_keyword"


def test_advance_supervisor_plan_marks_crawl_complete():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {})
    state: dict = {}
    plan = advance_supervisor_plan(plan, action="crawl_keyword", ok=True, state=state, brief=brief)
    assert plan["steps"][0]["status"] == "completed"
    assert plan["current_index"] == 1


def test_advance_supervisor_plan_query_stats_does_not_complete_evaluate_step():
    brief = TaskBrief(
        keyword="健身房",
        platform="douyin",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
    )
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True})
    plan["steps"][0]["status"] = "completed"
    plan["current_index"] = 1
    evaluate_step = plan["steps"][1]
    assert evaluate_step["action"] == "evaluate_leads"
    assert evaluate_step["status"] == "pending"

    plan = advance_supervisor_plan(
        plan,
        action="query_stats",
        ok=True,
        state={"crawl_done": True, "stats_synced": True},
        brief=brief,
    )
    assert evaluate_step["status"] == "pending"
    stats_step = next(s for s in plan["steps"] if s["action"] == "query_stats")
    assert stats_step["status"] == "completed"


def test_skill_flow_plan_after_crawl_returns_evaluate_leads():
    brief = TaskBrief(
        keyword="健身房",
        platform="douyin",
        goals={"target_leads": 5, "execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
    )
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True})
    plan["steps"][0]["status"] = "completed"
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        {"crawl_done": True},
    )
    assert decision is not None
    assert decision["action"] == "evaluate_leads"


def test_plan_complete_without_goal_becomes_suspend():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 10}, platform="douyin")
    plan = build_supervisor_execution_plan(brief, {"crawl_done": True, "stats_synced": True})
    for step in plan["steps"]:
        if step["action"] in {"crawl_keyword", "query_stats"}:
            step["status"] = "completed"
    plan["current_index"] = 2
    decision = plan_driven_supervisor_decision(
        plan,
        brief,
        {"crawl_done": True, "stats_synced": True, "leads_collected": 0},
    )
    assert decision is not None
    assert decision["action"] == "suspend"
    assert decision.get("completion_outcome") == "plan_incomplete"


def test_guard_complete_keeps_complete_when_goal_reached():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 3}, platform="douyin")
    decision = guard_supervisor_complete_decision(
        brief,
        {"leads_collected": 3},
        {"action": "complete", "reasoning": "done", "params": {}},
    )
    assert decision["action"] == "complete"
    assert decision.get("completion_outcome") == "goal_reached"


def test_guard_complete_uses_qualified_for_eval_task():
    brief = TaskBrief(
        keyword="健身",
        goals={"target_leads": 5, "agent_strategy": "standalone-browse-douyin"},
        platform="douyin",
    )
    decision = guard_supervisor_complete_decision(
        brief,
        {"leads_collected": 0, "leads_qualified": 5, "evaluation_done": True},
        {"action": "complete", "reasoning": "done", "params": {}},
    )
    assert decision["action"] == "complete"
    assert decision.get("completion_outcome") == "goal_reached"


def test_plan_incomplete_suspend_uses_qualified_metric():
    brief = TaskBrief(
        keyword="健身",
        goals={"target_leads": 5, "agent_strategy": "standalone-browse-douyin"},
        platform="douyin",
    )
    from app.services.task_execution_plan import build_plan_incomplete_suspend_decision

    decision = build_plan_incomplete_suspend_decision(
        brief,
        {"leads_collected": 2, "leads_qualified": 1},
    )
    assert decision["action"] == "suspend"
    assert "精准线索 1/5" in decision["reasoning"]


def test_infer_suspend_next_action_skill_flow_crawl_done_branch():
  brief = TaskBrief(
      keyword="淋浴房",
      goals={"target_leads": 5, "execution_mode": "skill_flow"},
      constraints={"termination_resume_next_day": True},
      platform="douyin",
  )
  state = {"crawl_done": True, "crawl_search_exhausted": False}
  next_action = infer_suspend_next_action("计划步骤失败，挂起等待人工处理", state, brief)
  assert "继续执行" in next_action or "reply" in next_action


def test_source_exhausted_suspend_next_action_and_note():
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 5}, platform="douyin")
    state = {
        "suspended": True,
        "completion_outcome": "source_exhausted",
        "crawl_search_exhausted": True,
        "leads_collected": 1,
        "wake_reason": "已扫完当前搜索列表仍无匹配评论",
    }
    next_action = infer_suspend_next_action(state["wake_reason"], state, brief)
    assert "评估标准" in next_action
    assert "降低目标数" in next_action

    note = build_execution_note(
        job_status="suspended",
        job_stage="track",
        job_result={
            "completion_outcome": "source_exhausted",
            "supervisor_state": state,
            "data_snapshot": {"progress": {"leads_collected": 1, "target_leads": 5}},
        },
    )
    assert note == "Supervisor 已挂起：搜索源已耗尽且未达成目标（1/5），请调整关键词或匹配条件。"


def test_round_mode_goal_uses_current_round_progress():
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 999, "repeat_mode": "round", "round_target_count": 2, "max_rounds": 3},
        constraints={"repeat_mode": "round", "round_target_count": 2, "max_rounds": 3},
        platform="douyin",
    )
    state = {"round_index": 1, "round_leads_collected": 2, "leads_collected": 2}
    assert supervisor_goal_reached(brief, state) is True


def test_standalone_can_auto_continue_with_saved_progress():
    from app.services.agent_strategy.registry import STANDALONE_BROWSE_DOUYIN
    from app.services.task_execution_plan import (
        build_plan_incomplete_suspend_decision,
        standalone_can_auto_continue,
    )

    brief = TaskBrief(
        keyword="健身",
        goals={"target_leads": 5, "agent_strategy": STANDALONE_BROWSE_DOUYIN.id},
        platform="douyin",
    )
    state = {
        "standalone_browse_offset": 12,
        "standalone_search_url": "https://www.douyin.com/search/健身",
        "leads_qualified": 0,
        "videos_processed": 12,
    }
    assert standalone_can_auto_continue(brief, state) is True
    decision = build_plan_incomplete_suspend_decision(brief, state)
    assert decision["completion_outcome"] == "plan_incomplete"
    assert decision["resume_at"] is not None
    assert "T" in str(decision["resume_at"])


def test_prepare_standalone_auto_continue_resets_crawl_step():
    from app.services.agent_strategy.registry import STANDALONE_BROWSE_DOUYIN
    from app.services.task_execution_plan import (
        build_standalone_execution_plan,
        prepare_standalone_auto_continue,
    )

    brief = TaskBrief(
        keyword="健身",
        goals={"target_leads": 5, "agent_strategy": STANDALONE_BROWSE_DOUYIN.id},
        platform="douyin",
    )
    state = {
        "suspended": True,
        "completion_outcome": "plan_incomplete",
        "crawl_done": True,
        "stats_synced": True,
        "standalone_browse_offset": 8,
        "execution_plan": build_standalone_execution_plan(brief, {}),
    }
    for step in state["execution_plan"]["steps"]:
        step["status"] = "completed"
    prepare_standalone_auto_continue(state, brief)
    assert state.get("suspended") is None
    assert state.get("crawl_done") is None
    crawl = next(s for s in state["execution_plan"]["steps"] if s["action"] == "crawl_keyword")
    assert crawl["status"] == "in_progress"
    assert state["execution_plan"]["current_index"] == 0


def test_effective_live_leads_qualified_merges_history_and_crawl_live():
    from app.services.task_round_service import effective_live_leads_qualified

    job_result = {
        "progress_events": [
            {"type": "crawl_progress", "data": {"leads_qualified": 4}},
        ]
    }
    state = {
        "leads_qualified": 0,
        "crawl_live": {"leads_qualified": 5},
    }
    assert effective_live_leads_qualified(state, job_result=job_result) == 5


def test_effective_live_leads_qualified_prefers_persisted_ids():
    from app.services.task_round_service import effective_live_leads_qualified

    state = {
        "leads_qualified": 36,
        "job_persisted_comment_ids": ["a", "b", "c", "d", "e"],
        "crawl_live": {"leads_qualified": 5},
    }
    assert effective_live_leads_qualified(state) == 5


def test_standalone_outreach_incomplete_when_qualified_but_not_collected():
    from app.services.standalone_browse_adapter import is_standalone_browse_brief
    from app.services.task_brief_service import TaskBrief
    from app.services.task_round_service import standalone_outreach_incomplete

    brief = TaskBrief(
        keyword="健身",
        title="上海健身",
        goals={"target_leads": 5, "agent_strategy": "standalone-browse-douyin"},
    )
    assert is_standalone_browse_brief(brief)
    state = {"leads_qualified": 5, "leads_collected": 0, "job_persisted_comment_ids": ["c1", "c2"]}
    assert standalone_outreach_incomplete(brief, state) is True
    state["leads_collected"] = 5
    assert standalone_outreach_incomplete(brief, state) is False
