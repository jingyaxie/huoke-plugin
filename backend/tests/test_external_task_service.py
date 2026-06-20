from __future__ import annotations

import pytest

from app.schemas.external_task import (
    ExternalTaskCreateRequest,
    ExternalTaskCorrelation,
    ExternalTaskOutreach,
    ExternalTaskScope,
)
from app.services.external_task_service import get_external_capabilities, normalize_external_create, resolve_intent


def test_capabilities_lists_three_intents():
    caps = get_external_capabilities()
    assert caps.schema_version == "huoke.external_task.v1"
    assert {item.intent for item in caps.intents} == {"keyword_auto", "single_video", "account_home"}
    assert "publish_time_range" in caps.field_options
    assert len(caps.field_options["comment_days"]) >= 3


def test_resolve_intent_from_lead_task_type():
    assert resolve_intent(intent=None, lead_task_type="video_manual") == "single_video"
    assert resolve_intent(intent=None, lead_task_type="home_manual") == "account_home"


def test_normalize_single_video_maps_publish_range():
    request = ExternalTaskCreateRequest(
        intent="single_video",
        name="单视频测试",
        platform="douyin",
        scope=ExternalTaskScope(
            input_url="https://www.douyin.com/video/123",
            comment_days=5,
            publish_time_range="7d",
        ),
        correlation=ExternalTaskCorrelation(external_task_id="task-1"),
    )
    message, config, correlation = normalize_external_create(request)
    assert "单视频" in message
    assert config["acquisition_mode"] == "single_video"
    assert config["video_url"] == "https://www.douyin.com/video/123"
    assert config["video_publish_days"] == 7
    assert correlation["external_task_id"] == "task-1"


def test_normalize_keyword_auto():
    request = ExternalTaskCreateRequest(
        intent="keyword_auto",
        name="团餐",
        platform="douyin",
        scope=ExternalTaskScope(keyword="团餐配送", region="深圳", target_count=20, comment_days=3),
        correlation=ExternalTaskCorrelation(external_task_id="task-2"),
    )
    _message, config, _correlation = normalize_external_create(request)
    assert config["keyword"] == "团餐配送"
    assert config["target_count"] == 20
    assert config["region"] == "深圳"


def test_capabilities_includes_evaluation():
    caps = get_external_capabilities()
    assert caps.evaluation_fields
    assert caps.evaluation_templates
    assert any(tpl.get("id") == "general_leads" for tpl in caps.evaluation_templates)


def test_normalize_passes_evaluation():
    from app.schemas.external_task import ExternalTaskEvaluation

    request = ExternalTaskCreateRequest(
        intent="keyword_auto",
        name="淋浴房",
        platform="douyin",
        scope=ExternalTaskScope(keyword="淋浴房", target_count=10),
        evaluation=ExternalTaskEvaluation(
            target_customer="装修业主",
            accept_description="询价、预约量房",
            reject_signals=["同行", "招聘"],
        ),
        correlation=ExternalTaskCorrelation(external_task_id="task-eval"),
    )
    _message, config, _correlation = normalize_external_create(request)
    assert config["evaluation"]["target_customer"] == "装修业主"
    assert "招聘" in config["evaluation"]["reject_signals"]


def test_normalize_outreach_templates():
    request = ExternalTaskCreateRequest(
        intent="single_video",
        name="单视频",
        platform="douyin",
        scope=ExternalTaskScope(input_url="https://www.douyin.com/video/1"),
        outreach=ExternalTaskOutreach(
            reply_templates=["评论A", "评论B"],
            dm_templates=["私信A"],
        ),
        correlation=ExternalTaskCorrelation(external_task_id="task-3"),
    )
    _message, config, _correlation = normalize_external_create(request)
    assert config["reply_templates"] == ["评论A", "评论B"]
    assert config["dm_templates"] == ["私信A"]
    assert config["constraints"]["reply_templates"] == ["评论A", "评论B"]


def test_normalize_crawl_headless():
    from app.schemas.external_task import ExternalTaskCrawl

    request = ExternalTaskCreateRequest(
        intent="keyword_auto",
        name="淋浴房",
        platform="douyin",
        scope=ExternalTaskScope(keyword="淋浴房", target_count=10),
        crawl=ExternalTaskCrawl(headless=False),
        correlation=ExternalTaskCorrelation(external_task_id="task-headed"),
    )
    _message, config, _correlation = normalize_external_create(request)
    assert config["crawl"] == {"headless": False}
