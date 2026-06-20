"""验证前端 build*TaskPayload 与后端 ExternalTaskCreateRequest / normalize 对齐。"""
from __future__ import annotations

from app.schemas.external_task import ExternalTaskCreateRequest
from app.services.external_task_service import normalize_external_create

DEFAULT_SETTINGS = {
    "comment_dm_interval_seconds_min": 10,
    "comment_dm_interval_seconds_max": 30,
    "comment_dm_percentage": 50,
    "follow_per_day": 30,
    "dm_per_day": 30,
    "batch_cooldown_minutes": 8,
}


def _build_constraints(settings, comment_preset_ids=None, dm_preset_ids=None, binding=None):
    constraints = {
        "comment_dm_interval_seconds_min": settings["comment_dm_interval_seconds_min"],
        "comment_dm_interval_seconds_max": settings["comment_dm_interval_seconds_max"],
        "comment_dm_percentage": settings["comment_dm_percentage"],
        "follow_per_day": settings["follow_per_day"],
        "dm_per_day": settings["dm_per_day"],
        "batch_cooldown_minutes": settings["batch_cooldown_minutes"],
    }
    if comment_preset_ids:
        constraints["comment_preset_ids"] = comment_preset_ids
    if dm_preset_ids:
        constraints["dm_preset_ids"] = dm_preset_ids
    if binding:
        constraints.update(binding)
    return constraints


def build_auto_task_payload_like_frontend():
    """镜像 frontend/src/api/externalTasks.js buildAutoTaskPayload。"""
    comment_presets = [{"id": "c1", "content": "评论模板A"}, {"id": "c2", "content": "评论模板B"}]
    dm_presets = [{"id": "d1", "content": "私信模板A"}]
    selected_comment_ids = ["c1"]
    selected_dm_ids = ["d1"]
    binding = {
        "huoke_account_id": "acc-1",
        "huoke_tenant_id": "default",
        "platform_user_id": "7123456789",
        "account_label": "测试账号",
    }

    return {
        "intent": "keyword_auto",
        "name": "深圳餐饮线索",
        "platform": "douyin",
        "scope": {
            "keyword": "团餐配送",
            "region": "深圳",
            "target_count": 50,
            "comment_days": 3,
            "publish_time_range": "7d",
        },
        "crawl": {"headless": True},
        "evaluation": {
            "target_customer": "餐饮老板",
            "accept_description": "询价、配送需求",
            "reject_signals": ["同行", "招聘"],
        },
        "outreach": {
            "constraints": _build_constraints(
                DEFAULT_SETTINGS,
                comment_preset_ids=selected_comment_ids,
                dm_preset_ids=selected_dm_ids,
                binding=binding,
            ),
            "reply_templates": [row["content"] for row in comment_presets if row["id"] in selected_comment_ids],
            "dm_templates": [row["content"] for row in dm_presets if row["id"] in selected_dm_ids],
        },
        "correlation": {
            "external_system": "huoke_local",
            "external_task_id": "auto-test-1",
            "idempotency_key": "auto-test-1",
        },
        "auto_execute": True,
        "auto_restart": True,
        "agent_strategy": "skill-flow-douyin",
    }


def build_manual_task_payload_like_frontend():
    return {
        "intent": "single_video",
        "name": "视频-abc123",
        "platform": "douyin",
        "scope": {
            "input_url": "https://www.douyin.com/video/7123456789",
            "comment_days": 5,
            "publish_time_range": "3d",
        },
        "crawl": {"headless": False},
        "outreach": {
            "constraints": _build_constraints(
                DEFAULT_SETTINGS,
                comment_preset_ids=["c1"],
                dm_preset_ids=["d1"],
            ),
            "reply_templates": ["评论模板A"],
            "dm_templates": ["私信模板A"],
        },
        "correlation": {
            "external_system": "huoke_local",
            "external_task_id": "manual-test-1",
            "idempotency_key": "manual-test-1",
        },
        "auto_execute": True,
        "auto_restart": True,
        "agent_strategy": "skill-flow-douyin",
    }


STANDALONE_STRATEGY = "standalone-browse-douyin"


def build_auto_task_payload_standalone_like_frontend():
    payload = build_auto_task_payload_like_frontend()
    payload["agent_strategy"] = STANDALONE_STRATEGY
    payload["scope"]["target_count"] = 5
    payload["scope"]["crawl_video_limit"] = 50
    return payload


def build_manual_task_payload_standalone_like_frontend():
    payload = build_manual_task_payload_like_frontend()
    payload["agent_strategy"] = STANDALONE_STRATEGY
    payload["scope"]["target_count"] = 3
    return payload


def build_account_home_payload_standalone_like_frontend():
    from tests.test_external_task_agent_e2e import build_account_home_payload_like_frontend

    payload = build_account_home_payload_like_frontend()
    payload["agent_strategy"] = STANDALONE_STRATEGY
    return payload


def test_frontend_auto_payload_validates_and_normalizes():
    raw = build_auto_task_payload_like_frontend()
    request = ExternalTaskCreateRequest.model_validate(raw)
    _message, config, correlation = normalize_external_create(request)

    assert request.intent == "keyword_auto"
    assert config["keyword"] == "团餐配送"
    assert config["region"] == "深圳"
    assert config["target_count"] == 50
    assert config["video_publish_days"] == 7
    assert config["crawl"] == {"headless": True}
    assert config["evaluation"]["target_customer"] == "餐饮老板"
    assert config["reply_templates"] == ["评论模板A"]
    assert config["dm_templates"] == ["私信模板A"]
    assert config["constraints"]["comment_preset_ids"] == ["c1"]
    assert config["constraints"]["interval_min"] == 10
    assert config["constraints"]["daily_dm_limit"] == 30
    assert config["constraints"]["huoke_account_id"] == "acc-1"
    assert correlation["external_system"] == "huoke_local"


def test_frontend_manual_payload_validates_and_normalizes():
    raw = build_manual_task_payload_like_frontend()
    request = ExternalTaskCreateRequest.model_validate(raw)
    _message, config, _correlation = normalize_external_create(request)

    assert config["acquisition_mode"] == "single_video"
    assert config["video_url"] == "https://www.douyin.com/video/7123456789"
    assert config["video_publish_days"] == 3
    assert config["crawl"] == {"headless": False}


def test_standalone_auto_payload_keeps_target_and_video_limit_separate():
    raw = build_auto_task_payload_standalone_like_frontend()
    request = ExternalTaskCreateRequest.model_validate(raw)
    _message, config, _correlation = normalize_external_create(request)
    assert config["target_count"] == 5
    assert config["crawl_video_limit"] == 50
    assert config["target_count"] != config["crawl_video_limit"]


def test_standalone_brief_omits_default_crawl_video_limit():
    from app.services.task_brief_service import _fallback_brief

    brief = _fallback_brief(
        '{"task_name":"测试","keyword":"健身","target_count":5,"platform":"douyin"}',
        agent_strategy=STANDALONE_STRATEGY,
    )
    assert brief.goals.get("target_leads") == 5
    assert "crawl_video_limit" not in brief.goals


def test_preflight_payload_shape_auto_execute_false():
    """预检 payload 与创建 payload 字段一致，仅 auto_execute 不同。"""
    raw = build_auto_task_payload_like_frontend()
    raw["auto_execute"] = False
    raw["correlation"]["external_task_id"] = "preflight-auto-test"
    request = ExternalTaskCreateRequest.model_validate(raw)
    assert request.auto_execute is False
    assert request.agent_strategy == "skill-flow-douyin"


# --- HTTP 集成测试 ---

from tests.helpers import API_HEADERS


def test_interaction_settings_api_roundtrip(api_client):
    get_resp = api_client.get("/api/settings/interaction", headers=API_HEADERS)
    assert get_resp.status_code == 200
    assert get_resp.json()["comment_dm_percentage"] == 50

    put_resp = api_client.put(
        "/api/settings/interaction",
        headers=API_HEADERS,
        json={"comment_dm_percentage": 70, "dm_per_day": 20},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["comment_dm_percentage"] == 70

    get_again = api_client.get("/api/settings/interaction", headers=API_HEADERS)
    assert get_again.json()["comment_dm_percentage"] == 70


def test_external_capabilities_api(api_client):
    resp = api_client.get("/api/agent/external/capabilities", headers=API_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == "huoke.external_task.v1"
    intents = {item["intent"] for item in body["intents"]}
    assert intents == {"keyword_auto", "single_video", "account_home"}


def test_preflight_auto_via_http(api_client):
    payload = build_auto_task_payload_like_frontend()
    payload["auto_execute"] = False
    resp = api_client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready"] is True
    check_ids = {item["id"] for item in body["checks"]}
    assert {"runtime", "login", "llm", "orchestration", "evaluation"}.issubset(check_ids)


def test_preflight_manual_via_http(api_client):
    payload = build_manual_task_payload_like_frontend()
    payload["auto_execute"] = False
    resp = api_client.post("/api/agent/external/preflight", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ready"] is True
    actions = [row.get("action") for row in (body.get("orchestration") or {}).get("steps", [])]
    assert "crawl_content_url" in actions


def test_create_external_job_via_http(api_client, monkeypatch):
    captured: dict = {}

    async def fake_submit_async(self, **kwargs):
        captured.update(kwargs)
        from datetime import datetime, timezone
        from app.services.agent_async_job_service import AgentAsyncJob

        now = datetime.now(timezone.utc)
        return AgentAsyncJob(
            job_id="job-test-001",
            tenant_id=kwargs.get("tenant_id", "default"),
            platform=kwargs.get("platform", "douyin"),
            account_id=kwargs.get("account_id", "default"),
            message=kwargs.get("message", ""),
            provider=kwargs.get("provider", "deepseek"),
            mode=kwargs.get("mode", "agent"),
            run_mode=kwargs.get("run_mode", "auto"),
            auto_execute=kwargs.get("auto_execute", True),
            auto_restart=kwargs.get("auto_restart", True),
            agent_strategy=kwargs.get("agent_strategy"),
            status="queued",
            created_at=now,
            updated_at=now,
            correlation=kwargs.get("correlation") or {},
            result={"config": kwargs.get("config") or {}},
        )

    monkeypatch.setattr(
        "app.api.agent_routes.AgentAsyncJobService.submit_async",
        fake_submit_async,
    )

    payload = build_auto_task_payload_like_frontend()
    resp = api_client.post("/api/agent/external/jobs", headers=API_HEADERS, json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_id"] == "job-test-001"

    config = captured["config"]
    assert config["keyword"] == "团餐配送"
    assert config["evaluation"]["target_customer"] == "餐饮老板"
    assert config["constraints"]["comment_preset_ids"] == ["c1"]
    assert config["reply_templates"] == ["评论模板A"]
    assert captured["agent_strategy"] == "skill-flow-douyin"
