from __future__ import annotations

from app.services.supervisor_outreach import outreach_interval_from_brief
from app.services.supervisor_outreach_helpers import (
    build_dm_text,
    build_reply_text,
    comment_match_from_brief,
    min_comment_digg_from_brief,
    next_outreach_action_from_brief,
    outreach_priority_from_brief,
    skip_replied_comments_enabled,
)
from app.services.supervisor_action_guard import configured_outreach_actions, guard_supervisor_action
from app.services.task_brief_service import TaskBrief


def test_lead_evaluation_includes_min_digg():
    brief = TaskBrief(
        platform="douyin",
        goals={"min_comment_digg": 3},
        constraints={
            "lead_evaluation": {
                "schema": "huoke.lead_evaluation.v1",
                "version": 1,
                "spec_hash": "sha256:test",
                "criteria": {"min_comment_length": 4},
                "thresholds": {"precise": 0.72, "outreach": 0.55},
            }
        },
    )
    spec = comment_match_from_brief(brief)
    assert spec.get("min_comment_digg") == 3
    assert min_comment_digg_from_brief(brief) == 3


def test_outreach_interval_reads_interval_min_alias():
    brief = TaskBrief(constraints={"interval_min": 10, "interval_max": 30})
    assert outreach_interval_from_brief(brief) == (10, 30)


def test_outreach_priority_order():
    brief = TaskBrief(
        constraints={"outreach_priority": ["dm", "reply", "follow"]},
    )
    assert outreach_priority_from_brief(brief) == ["dm", "reply", "follow"]
    stats = {
        "reply": {"can_do": True},
        "dm": {"can_do": True},
        "follow": {"can_do": True},
    }
    assert next_outreach_action_from_brief(stats, brief) == "dm"


def test_reply_and_dm_templates_separate():
    brief = TaskBrief(
        constraints={
            "reply_template": "{{nickname}}，专业简短",
            "dm_template": "您好 {{nickname}}，方便聊聊吗？",
        }
    )
    assert "专业简短" in build_reply_text(brief, nickname="张三", comment="团餐")
    assert "方便聊聊" in build_dm_text(brief, nickname="张三", comment="团餐")


def test_reply_and_dm_templates_random_pool():
    brief = TaskBrief(
        constraints={
            "reply_templates": ["评论A {{nickname}}", "评论B {{nickname}}"],
            "dm_templates": ["私信A {{nickname}}", "私信B {{nickname}}"],
        }
    )
    reply = build_reply_text(brief, nickname="张三", comment="团餐")
    dm = build_dm_text(brief, nickname="张三", comment="团餐")
    assert reply.startswith("评论A") or reply.startswith("评论B")
    assert dm.startswith("私信A") or dm.startswith("私信B")


def test_skip_replied_default_true():
    brief = TaskBrief()
    assert skip_replied_comments_enabled(brief) is True
    brief.constraints["skip_replied_comments"] = False
    assert skip_replied_comments_enabled(brief) is False


def test_configured_outreach_actions_intersects_priority():
    brief = TaskBrief(
        constraints={
            "actions_on_match": [{"type": "reply"}, {"type": "follow"}],
            "outreach_priority": ["reply"],
        }
    )
    assert configured_outreach_actions(brief) == {"reply"}


def test_guard_blocks_outreach_before_crawl():
    brief = TaskBrief(keyword="团餐", platform="douyin")
    decision = guard_supervisor_action(
        {"action": "reply", "params": {"comment_id": "c1"}},
        brief=brief,
        state={},
    )
    assert decision["action"] == "crawl_keyword"


def test_guard_blocks_outreach_before_evaluation():
    brief = TaskBrief(
        keyword="团餐",
        platform="douyin",
        goals={"execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
    )
    decision = guard_supervisor_action(
        {"action": "reply", "params": {"comment_id": "c1"}},
        brief=brief,
        state={"crawl_done": True},
    )
    assert decision["action"] == "evaluate_leads"


def test_guard_blocks_manual_outreach_before_evaluation():
    brief = TaskBrief(
        title="单视频",
        platform="douyin",
        goals={
            "acquisition_mode": "single_video",
            "input_url": "https://www.douyin.com/video/1",
            "video_url": "https://www.douyin.com/video/1",
        },
    )
    decision = guard_supervisor_action(
        {"action": "reply", "params": {"comment_id": "c1"}},
        brief=brief,
        state={"crawl_done": True},
    )
    assert decision["action"] == "evaluate_leads"


def test_guard_blocks_outreach_before_stats():
    brief = TaskBrief(keyword="团餐", platform="douyin")
    decision = guard_supervisor_action(
        {"action": "reply", "params": {"comment_id": "c1"}},
        brief=brief,
        state={"crawl_done": True, "evaluation_done": True},
    )
    assert decision["action"] == "query_stats"


def test_guard_redirects_query_stats_to_evaluate_after_crawl():
    brief = TaskBrief(
        keyword="健身房",
        platform="douyin",
        goals={"execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
    )
    decision = guard_supervisor_action(
        {"action": "query_stats", "params": {"platform": "douyin"}},
        brief=brief,
        state={"crawl_done": True},
    )
    assert decision["action"] == "evaluate_leads"


def test_guard_redirects_repeat_crawl_to_evaluate_not_query_stats():
    brief = TaskBrief(
        keyword="健身房",
        platform="douyin",
        goals={"execution_mode": "skill_flow", "agent_strategy": "skill-flow-douyin"},
    )
    decision = guard_supervisor_action(
        {"action": "crawl_keyword", "params": {"keyword": "健身房"}},
        brief=brief,
        state={"crawl_done": True},
    )
    assert decision["action"] == "evaluate_leads"


def test_guard_blocks_unconfigured_outreach_action():
    brief = TaskBrief(
        keyword="团餐",
        platform="douyin",
        constraints={
            "actions_on_match": [{"type": "reply", "template": "hi"}],
            "outreach_priority": ["reply"],
        },
    )
    decision = guard_supervisor_action(
        {"action": "dm", "params": {"message": "hi"}},
        brief=brief,
        state={"crawl_done": True, "evaluation_done": True, "stats_synced": True},
    )
    assert decision["action"] == "reply"
    assert "不允许 dm" in decision["reasoning"]


def test_guard_suspends_when_configured_quota_exhausted():
    brief = TaskBrief(
        keyword="团餐",
        platform="douyin",
        constraints={
            "actions_on_match": [{"type": "reply"}],
            "outreach_priority": ["reply"],
        },
    )
    decision = guard_supervisor_action(
        {"action": "reply", "params": {"comment_id": "c1"}},
        brief=brief,
        state={"crawl_done": True, "evaluation_done": True, "stats_synced": True},
        stats={"reply": {"can_do": False, "count": 2, "limit": 2}},
    )
    assert decision["action"] == "suspend"
    assert decision["completion_outcome"] == "quota_exhausted"


def test_guard_complete_when_goal_not_met_becomes_suspend():
    brief = TaskBrief(goals={"target_leads": 3})
    decision = guard_supervisor_action(
        {"action": "complete", "reasoning": "完成"},
        brief=brief,
        state={"leads_collected": 1},
    )
    assert decision["action"] == "suspend"
