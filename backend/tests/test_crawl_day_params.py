from __future__ import annotations

from app.services.external_task_service import INTENT_SPECS
from app.services.supervisor_crawl_helpers import (
    build_crawl_day_params,
    comment_capture_days_from,
    crawl_step_params,
    video_publish_days_from,
)
from app.services.task_brief_service import TaskBrief


def _brief(**goals) -> TaskBrief:
    return TaskBrief(keyword="健身房", region="北京", goals=goals)


def test_publish_and_comment_days_both_apply():
    brief = _brief(video_publish_days=7, comment_days=3)
    assert video_publish_days_from(brief) == 7
    assert comment_capture_days_from(brief) == 3
    assert build_crawl_day_params(brief) == {"video_publish_days": 7, "comment_days": 3}


def test_unlimited_publish_keeps_comment_days_only():
    brief = _brief(comment_days=7)
    assert video_publish_days_from(brief) is None
    assert comment_capture_days_from(brief) == 7
    assert build_crawl_day_params(brief) == {"comment_days": 7}


def test_crawl_step_params_no_ambiguous_days_key():
    params = crawl_step_params(_brief(video_publish_days=7, comment_days=3))
    assert "days" not in params
    assert params["video_publish_days"] == 7
    assert params["comment_days"] == 3


def test_keyword_auto_capabilities_include_publish_time_range():
    spec = next(item for item in INTENT_SPECS if item.intent == "keyword_auto")
    keys = {field.key for field in spec.scope_fields}
    assert "publish_time_range" in keys
    assert "comment_days" in keys
