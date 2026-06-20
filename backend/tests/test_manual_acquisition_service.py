from __future__ import annotations

import pytest

from app.services.manual_acquisition_service import (
    build_manual_acquisition_plan,
    enrich_manual_acquisition_brief,
    manual_acquisition_mode,
)
from app.services.task_brief_service import TaskBrief


def test_manual_acquisition_mode_from_payload():
    brief = TaskBrief(title="手动", platform="douyin", goals={})
    brief = enrich_manual_acquisition_brief(
        brief,
        {
            "acquisition_mode": "single_video",
            "input_url": "https://www.douyin.com/video/1",
            "comment_days": 5,
        },
    )
    assert manual_acquisition_mode(brief) == "single_video"
    assert brief.goals["video_url"] == "https://www.douyin.com/video/1"
    assert brief.goals["input_url"] == "https://www.douyin.com/video/1"


def test_build_manual_single_video_plan():
    brief = TaskBrief(
        title="单视频",
        platform="douyin",
        goals={
            "acquisition_mode": "single_video",
            "input_url": "https://www.douyin.com/video/1",
            "comment_days": 3,
            "target_leads": 10,
        },
        constraints={"outreach_priority": ["reply", "dm", "follow"]},
    )
    plan = build_manual_acquisition_plan(brief, {})
    assert plan is not None
    assert plan["pipeline"] == "manual_single_video"
    assert plan["steps"][0]["action"] == "crawl_content_url"
    assert plan["steps"][0]["params"]["video_url"] == "https://www.douyin.com/video/1"
    assert plan["steps"][1]["action"] == "evaluate_leads"
    assert any(step["action"] == "reply" for step in plan["steps"])


def test_build_manual_account_home_plan():
    brief = TaskBrief(
        title="账号",
        platform="douyin",
        goals={
            "acquisition_mode": "account_home",
            "profile_url": "https://www.douyin.com/user/MS4w",
            "comment_days": 3,
            "crawl_video_limit": 8,
        },
        constraints={"outreach_priority": ["reply"]},
    )
    plan = build_manual_acquisition_plan(brief, {})
    assert plan is not None
    assert plan["pipeline"] == "manual_account_home"
    assert plan["steps"][0]["action"] == "crawl_profile"
    assert plan["steps"][0]["params"]["profile_url"] == "https://www.douyin.com/user/MS4w"
    assert plan["steps"][0]["params"]["crawl_video_limit"] == 8
    assert plan["steps"][1]["action"] == "evaluate_leads"


def test_enrich_manual_maps_publish_time_range_and_splits_comment_days():
    brief = TaskBrief(title="手动", platform="douyin", goals={})
    brief = enrich_manual_acquisition_brief(
        brief,
        {
            "acquisition_mode": "single_video",
            "input_url": "https://www.douyin.com/video/1",
            "publish_time_range": "7d",
            "comment_days": 3,
        },
    )
    assert brief.goals["video_publish_days"] == 7
    assert brief.goals["comment_days"] == 3

    plan = build_manual_acquisition_plan(brief, {})
    assert plan is not None
    params = plan["steps"][0]["params"]
    assert params["video_publish_days"] == 7
    assert params["comment_days"] == 3
    assert "days" not in params


def test_infer_manual_url_mode_profile():
    from app.services.manual_acquisition_service import infer_manual_url_mode

    url = "https://www.douyin.com/user/MS4wLjABAAAAR-hiJNkDpOJIXZ7D"
    assert infer_manual_url_mode(url, "douyin") == "account_home"


def test_infer_manual_url_mode_douyin_short_link():
    from app.services.manual_acquisition_service import infer_manual_url_mode

    assert infer_manual_url_mode("https://v.douyin.com/fDELcUzXDCA/", "douyin") == "account_home"


def test_enrich_manual_reconciles_profile_url_for_single_video_intent():
    brief = TaskBrief(title="手动", platform="douyin", goals={})
    profile = "https://www.douyin.com/user/MS4wLjABAAAAR-hiJNkDpOJIXZ7D"
    brief = enrich_manual_acquisition_brief(
        brief,
        {
            "acquisition_mode": "single_video",
            "input_url": profile,
            "comment_days": 3,
            "crawl_video_limit": 10,
        },
    )
    assert manual_acquisition_mode(brief) == "account_home"
    assert brief.goals["profile_url"] == profile
    plan = build_manual_acquisition_plan(brief, {})
    assert plan is not None
    assert plan["steps"][0]["action"] == "crawl_profile"
