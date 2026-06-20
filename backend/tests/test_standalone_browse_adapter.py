from __future__ import annotations

from app.services.agent_strategy.registry import (
    SKILL_FLOW_DOUYIN,
    STANDALONE_BROWSE_DOUYIN,
)
from app.services.standalone_browse_adapter import (
    STANDALONE_BROWSE_STRATEGY_ID,
    brief_to_standalone_config,
    build_standalone_execution_plan,
    is_standalone_browse_brief,
    standalone_result_to_skill_result,
    upgrade_standalone_execution_plan,
)
from app.services.task_brief_service import TaskBrief
from app.platforms.douyin.standalone_keyword_browse import (
    PreciseLeadRecord,
    StandaloneKeywordBrowseResult,
)


def _brief(**kwargs) -> TaskBrief:
    goals = kwargs.pop("goals", {})
    constraints = kwargs.pop("constraints", {})
    return TaskBrief(
        title=kwargs.get("title", "测试"),
        keyword=kwargs.get("keyword", "淋浴房"),
        platform=kwargs.get("platform", "douyin"),
        agent_strategy=kwargs.get("agent_strategy", STANDALONE_BROWSE_STRATEGY_ID),
        goals={"target_leads": 3, **goals},
        constraints=constraints,
    )


def test_is_standalone_browse_brief_only_for_explicit_strategy():
    assert is_standalone_browse_brief(_brief(agent_strategy=STANDALONE_BROWSE_STRATEGY_ID))
    assert not is_standalone_browse_brief(_brief(agent_strategy=SKILL_FLOW_DOUYIN.id))
    assert is_standalone_browse_brief(_brief(agent_strategy="", goals={"use_standalone_browse": True}))


def test_brief_to_standalone_config_keyword_mode():
    cfg = brief_to_standalone_config(_brief(), {}, action="crawl_keyword")
    assert cfg.acquisition_mode == "keyword_auto"
    assert cfg.keyword == "淋浴房"
    assert cfg.target_precise_leads == 3
    assert cfg.execute_outreach is True


def test_brief_to_standalone_config_profile_mode():
    cfg = brief_to_standalone_config(
        _brief(
            keyword="",
            goals={
                "acquisition_mode": "account_home",
                "profile_url": "https://www.douyin.com/user/test",
                "target_leads": 2,
            },
        ),
        {},
        action="crawl_profile",
    )
    assert cfg.acquisition_mode == "account_home"
    assert "user/test" in cfg.profile_url


def test_standalone_execution_plan_includes_post_crawl_outreach():
    plan = build_standalone_execution_plan(_brief())
    actions = [s["action"] for s in plan["steps"]]
    assert actions[0] == "crawl_keyword"
    assert actions[1] == "query_stats"
    assert "reply" in actions
    assert "complete" in actions[-1] or actions[-1] == "complete"
    assert plan["pipeline"] == "standalone_browse"
    crawl = plan["steps"][0]
    assert "精准线索" in crawl["label"]
    assert "最多 5 个视频" not in crawl["label"]
    assert crawl["params"].get("max_videos_to_browse") == 200
    assert crawl["params"].get("target_leads") == 3


def test_upgrade_standalone_execution_plan_replaces_misleading_video_cap():
    old = {
        "pipeline": "standalone_browse",
        "version": 2,
        "steps": [
            {
                "id": "crawl",
                "action": "crawl_keyword",
                "label": "关键词「健身」一体化浏览；最多 5 个视频",
                "status": "failed",
                "params": {
                    "keyword": "健身",
                    "crawl_video_limit": 5,
                    "video_limit": 5,
                    "limit": 5,
                },
            },
            {"id": "sync_stats", "action": "query_stats", "status": "pending", "params": {}},
            {"id": "finish", "action": "complete", "status": "pending", "params": {}},
        ],
        "current_index": 0,
    }
    upgraded = upgrade_standalone_execution_plan(old, _brief(keyword="健身", goals={"target_leads": 5}))
    crawl = upgraded["steps"][0]
    assert upgraded["version"] == 4
    assert "精准线索" in crawl["label"]
    assert "最多 5 个视频" not in crawl["label"]
    assert crawl["params"]["max_videos_to_browse"] == 200
    assert crawl["params"]["target_leads"] == 5
    assert crawl["status"] == "failed"


def test_standalone_partial_without_target_keeps_crawling():
    result = StandaloneKeywordBrowseResult(
        ok=False,
        keyword="健身",
        acquisition_mode="keyword_auto",
        videos_processed=1,
        comments_scanned=12,
        precise_leads=[],
        target_reached=False,
        search_exhausted=False,
        diagnostic="未凑够目标：精准线索 0/5，已浏览 1 个视频（本批上限 5）；搜索列表仍有视频，将继续浏览",
    )
    skill = standalone_result_to_skill_result(result, brief=_brief(goals={"target_leads": 5}), action="crawl_keyword")
    assert skill["status"] == "partial"
    assert skill.get("error") is None
    assert skill.get("standalone_need_more") is True
    assert skill.get("crawl_search_exhausted") is False


def test_standalone_search_exhausted_marks_suspend_signal():
    result = StandaloneKeywordBrowseResult(
        ok=False,
        keyword="健身",
        acquisition_mode="keyword_auto",
        videos_processed=3,
        comments_scanned=20,
        precise_leads=[],
        target_reached=False,
        search_exhausted=True,
        error="E_TARGET_NOT_MET",
        diagnostic="未凑够目标：精准线索 0/5，已浏览 3 个视频（本批上限 5）",
    )
    skill = standalone_result_to_skill_result(result, brief=_brief(goals={"target_leads": 5}), action="crawl_keyword")
    assert skill.get("error") == "E_TARGET_NOT_MET"
    assert skill.get("crawl_search_exhausted") is True
    assert not skill.get("standalone_need_more")


def test_brief_to_standalone_config_scales_comment_scroll_with_target():
    cfg = brief_to_standalone_config(_brief(goals={"target_leads": 5}), {}, action="crawl_keyword")
    assert cfg.max_comments_per_video >= 200
    assert cfg.comment_scroll_rounds >= 40


def test_brief_to_standalone_config_maps_form_fields():
    brief = _brief(
        keyword="淋浴房",
        region="深圳",
        goals={
            "target_leads": 8,
            "comment_days": 5,
            "video_publish_days": 7,
        },
        constraints={
            "comment_dm_percentage": 40,
            "comment_dm_interval_seconds_min": 12,
            "comment_dm_interval_seconds_max": 24,
            "follow_per_day": 20,
            "dm_per_day": 15,
            "reply_templates": ["您好 {{nickname}}"],
            "dm_templates": ["你好 {{nickname}}"],
            "lead_evaluation": {
                "schema": "huoke.lead_evaluation.v1",
                "evaluation_mode": "llm_intent",
                "reject_signals": ["招聘", "广告"],
            },
        },
    )
    cfg = brief_to_standalone_config(
        brief,
        {"keyword": "淋浴房", "region": "深圳"},
        action="crawl_keyword",
    )
    assert cfg.region == "深圳"
    assert cfg.target_precise_leads == 8
    assert cfg.max_videos_to_browse == 200
    assert cfg.content_limit >= 10
    assert cfg.comment_days == 5
    assert cfg.video_publish_days == 7
    assert cfg.use_llm_eval is True
    assert cfg.reply_text == "您好 {{nickname}}"
    assert cfg.dm_text == "你好 {{nickname}}"
    assert cfg.action_policy["interval_min_sec"] == 12
    assert cfg.action_policy["interval_max_sec"] == 24
    assert "招聘" in cfg.exclude_keywords


def test_target_leads_not_used_as_video_cap():
    """target_count=5 是精准线索目标，不应把单步浏览上限也压成 5。"""
    brief = _brief(keyword="健身", goals={"target_leads": 5, "comment_days": 7})
    cfg = brief_to_standalone_config(brief, {"keyword": "健身", "crawl_video_limit": 5}, action="crawl_keyword")
    assert cfg.target_precise_leads == 5
    assert cfg.max_videos_to_browse == 200
    lead = PreciseLeadRecord(
        comment_id="c1",
        comment_text="淋浴房报价",
        username="u1",
        user_id="u1",
        sec_uid="sec1",
        video_url="https://www.douyin.com/video/1",
        aweme_id="1",
        create_time=1,
        match_score=1.0,
        match_reason="kw",
        planned_action="reply",
        outreach_executed=True,
        raw_comment={"comment_id": "c1", "comment": "淋浴房报价"},
    )
    result = StandaloneKeywordBrowseResult(
        ok=True,
        keyword="淋浴房",
        acquisition_mode="keyword_auto",
        videos_processed=2,
        comments_scanned=10,
        precise_leads=[lead],
        target_reached=True,
    )
    skill = standalone_result_to_skill_result(result, brief=_brief(), action="crawl_keyword")
    assert skill["standalone_browse"] is True
    assert skill["precise_lead_count"] == 1
    assert skill["results"]
    assert skill["inline_outreach"]["executed"] == 1
