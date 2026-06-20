"""创建任务 → 智能体 external API 端到端对齐测试。"""
from __future__ import annotations

import pytest

from app.schemas.external_task import ExternalTaskCreateRequest
from app.services.external_task_service import normalize_external_create
from tests.helpers import API_HEADERS
from tests.test_frontend_payload_alignment import (
    DEFAULT_SETTINGS,
    build_auto_task_payload_like_frontend,
    build_manual_task_payload_like_frontend,
)


def _build_constraints(**extra):
    base = {
        "comment_dm_interval_seconds_min": DEFAULT_SETTINGS["comment_dm_interval_seconds_min"],
        "comment_dm_interval_seconds_max": DEFAULT_SETTINGS["comment_dm_interval_seconds_max"],
        "comment_dm_percentage": DEFAULT_SETTINGS["comment_dm_percentage"],
        "follow_per_day": DEFAULT_SETTINGS["follow_per_day"],
        "dm_per_day": DEFAULT_SETTINGS["dm_per_day"],
        "batch_cooldown_minutes": DEFAULT_SETTINGS["batch_cooldown_minutes"],
        "comment_preset_ids": ["c1"],
        "dm_preset_ids": ["d1"],
    }
    base.update(extra)
    return base


def build_account_home_payload_like_frontend():
    return {
        "intent": "account_home",
        "name": "博主主页获客",
        "platform": "douyin",
        "scope": {
            "input_url": "https://www.douyin.com/user/MS4wLjABAAAAtest",
            "comment_days": 7,
            "publish_time_range": "7d",
            "crawl_video_limit": 5,
        },
        "crawl": {"headless": True},
        "evaluation": {
            "target_customer": "意向客户",
            "accept_description": "咨询、询价",
            "reject_signals": ["广告"],
        },
        "outreach": {
            "constraints": _build_constraints(),
            "reply_templates": ["评论模板A"],
            "dm_templates": ["私信模板A"],
        },
        "correlation": {
            "external_system": "huoke_local",
            "external_task_id": "account-home-test-1",
            "idempotency_key": "account-home-test-1",
        },
        "auto_execute": True,
        "auto_restart": True,
        "agent_strategy": "skill-flow-douyin",
    }


XHS_NOTE_URL = "https://www.xiaohongshu.com/explore/6a07f7370000000007021584"
XHS_PROFILE_URL = "https://www.xiaohongshu.com/user/profile/634157fa000000001802ff07"


def build_xhs_auto_payload():
    payload = build_auto_task_payload_like_frontend()
    payload["platform"] = "xiaohongshu"
    payload["agent_strategy"] = "skill-flow-xiaohongshu"
    payload["correlation"]["external_task_id"] = "xhs-auto-test"
    payload["correlation"]["idempotency_key"] = "xhs-auto-test"
    return payload


def build_xhs_manual_payload():
    payload = build_manual_task_payload_like_frontend()
    payload["platform"] = "xiaohongshu"
    payload["scope"]["input_url"] = XHS_NOTE_URL
    payload["agent_strategy"] = "skill-flow-xiaohongshu"
    payload["correlation"]["external_task_id"] = "xhs-manual-test"
    payload["correlation"]["idempotency_key"] = "xhs-manual-test"
    return payload


def build_xhs_account_home_payload():
    payload = build_account_home_payload_like_frontend()
    payload["platform"] = "xiaohongshu"
    payload["scope"]["input_url"] = XHS_PROFILE_URL
    payload["agent_strategy"] = "skill-flow-xiaohongshu"
    payload["correlation"]["external_task_id"] = "xhs-account-home-test"
    payload["correlation"]["idempotency_key"] = "xhs-account-home-test"
    return payload


AUTO_EXPECTED_CONFIG_KEYS = {
    "intent",
    "acquisition_mode",
    "platform",
    "task_name",
    "keyword",
    "region",
    "target_count",
    "comment_days",
    "video_publish_days",
    "crawl",
    "evaluation",
    "constraints",
    "reply_templates",
    "dm_templates",
    "correlation",
}


def test_all_intents_validate_and_normalize():
    payloads = [
        build_auto_task_payload_like_frontend(),
        build_manual_task_payload_like_frontend(),
        build_account_home_payload_like_frontend(),
    ]
    for raw in payloads:
        request = ExternalTaskCreateRequest.model_validate(raw)
        message, config, correlation = normalize_external_create(request)
        assert message
        assert config["intent"] == raw["intent"]
        assert config["acquisition_mode"] == raw["intent"]
        assert correlation["external_task_id"] == raw["correlation"]["external_task_id"]


def test_account_home_normalizes_profile_url():
    raw = build_account_home_payload_like_frontend()
    request = ExternalTaskCreateRequest.model_validate(raw)
    _message, config, _correlation = normalize_external_create(request)
    url = raw["scope"]["input_url"]
    assert config["profile_url"] == url
    assert config["crawl_video_limit"] == 5


@pytest.mark.parametrize(
    "builder,expected_strategy",
    [
        (build_auto_task_payload_like_frontend, "skill-flow-douyin"),
        (build_xhs_auto_payload, "skill-flow-xiaohongshu"),
    ],
)
def test_create_job_agent_strategy(api_client, capture_submit, builder, expected_strategy):
    payload = builder()
    resp = api_client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    assert capture_submit["agent_strategy"] == expected_strategy
    assert capture_submit["auto_execute"] is True
    assert capture_submit["auto_restart"] is True
    assert capture_submit["mode"] == "agent"


def test_create_manual_job_via_http(api_client, capture_submit):
    payload = build_manual_task_payload_like_frontend()
    resp = api_client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text

    config = capture_submit["config"]
    assert config["acquisition_mode"] == "single_video"
    assert config["video_url"] == payload["scope"]["input_url"]
    assert config["video_publish_days"] == 3
    assert config["dm_templates"] == ["私信模板A"]


def test_create_account_home_job_via_http(api_client, capture_submit):
    payload = build_account_home_payload_like_frontend()
    resp = api_client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text

    config = capture_submit["config"]
    assert config["acquisition_mode"] == "account_home"
    assert config["profile_url"] == payload["scope"]["input_url"]
    assert config["crawl_video_limit"] == 5
    assert config["evaluation"]["target_customer"] == "意向客户"


def test_create_auto_job_full_config_passthrough(api_client, capture_submit):
    payload = build_auto_task_payload_like_frontend()
    resp = api_client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text

    config = capture_submit["config"]
    missing = AUTO_EXPECTED_CONFIG_KEYS - set(config.keys())
    assert not missing, f"缺少 config 字段: {missing}"

    assert config["keyword"] == "团餐配送"
    assert config["region"] == "深圳"
    assert config["target_count"] == 50
    assert config["comment_days"] == 3
    assert config["video_publish_days"] == 7
    assert config["crawl"] == {"headless": True}
    assert config["constraints"]["huoke_account_id"] == "acc-1"
    assert config["constraints"]["interval_min"] == 10
    assert config["constraints"]["daily_dm_limit"] == 30
    assert capture_submit["correlation"]["external_system"] == "huoke_local"


@pytest.mark.parametrize(
    "builder",
    [
        build_auto_task_payload_like_frontend,
        build_manual_task_payload_like_frontend,
        build_account_home_payload_like_frontend,
    ],
)
def test_preflight_all_intents_ready(api_client, builder):
    payload = builder()
    payload["auto_execute"] = False
    resp = api_client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready"] is True
    assert body["blocking_count"] == 0
    blocking = [row for row in body["checks"] if row.get("blocking")]
    assert not blocking, blocking
    assert body.get("orchestration")
    assert body.get("evaluation")


def test_capabilities_supports_frontend_task_types(api_client):
    resp = api_client.get("/api/agent/external/capabilities", headers=API_HEADERS)
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.get("platforms") or []) >= {"douyin", "xiaohongshu"}
    intents = {item["intent"]: item for item in body["intents"]}
    assert set(intents) == {"keyword_auto", "single_video", "account_home"}

    auto_types = set(intents["keyword_auto"].get("lead_task_types") or [])
    assert "home_auto" in auto_types
    manual_types = set(intents["single_video"].get("lead_task_types") or []) | set(
        intents["account_home"].get("lead_task_types") or [],
    )
    assert {"video_manual", "home_manual"}.issubset(manual_types)

    field_options = body.get("field_options") or {}
    assert "comment_days" in field_options
    assert "publish_time_range" in field_options
    assert body.get("evaluation_fields")
    assert body.get("evaluation_templates")


def test_invalid_payload_rejected(api_client):
    resp = api_client.post(
        "/api/agent/external/jobs",
        headers=API_HEADERS,
        json={"intent": "keyword_auto", "name": "缺 correlation"},
    )
    assert resp.status_code == 422


def test_preflight_blocks_missing_keyword(api_client):
    payload = build_auto_task_payload_like_frontend()
    payload["scope"]["keyword"] = ""
    payload["auto_execute"] = False
    resp = api_client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is False
    scope_check = next(row for row in body["checks"] if row["id"] == "scope")
    assert scope_check["status"] == "error"
