from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.config import get_settings
from app.main import app
from app.services.page_diagnosis.reporter import CrawlFailureReporter
from tests.conftest import _build_test_settings, _install_api_settings, _install_fake_login_store
from tests.helpers import API_HEADERS

_DISABLED_PAYLOAD = {
    "enabled": False,
    "llm_enabled": False,
    "screenshot_enabled": False,
    "llm_timeout_seconds": 12,
    "rule_confidence_skip_llm": 0.88,
}


@pytest.fixture
def disabled_page_diagnosis_via_api(api_client):
    get_resp = api_client.get("/api/settings/page-diagnosis", headers=API_HEADERS)
    assert get_resp.status_code == 200
    assert get_resp.json()["enabled"] is True

    put_resp = api_client.put(
        "/api/settings/page-diagnosis",
        headers=API_HEADERS,
        json=_DISABLED_PAYLOAD,
    )
    assert put_resp.status_code == 200
    return put_resp.json()


def test_page_diagnosis_settings_api_roundtrip(api_client, disabled_page_diagnosis_via_api):
    updated = disabled_page_diagnosis_via_api
    assert updated["enabled"] is False
    assert updated["llm_timeout_seconds"] == 12
    assert updated["rule_confidence_skip_llm"] == 0.88

    get_again = api_client.get("/api/settings/page-diagnosis", headers=API_HEADERS)
    assert get_again.status_code == 200
    assert get_again.json() == updated


def test_page_diagnosis_settings_persist_to_json(tmp_path, disabled_page_diagnosis_via_api):
    settings = config.get_settings()
    config_path = settings.storage_root / "settings" / "page_diagnosis.json"
    assert config_path.is_file()
    assert str(settings.storage_root).startswith(str(tmp_path))

    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored == disabled_page_diagnosis_via_api


def test_page_diagnosis_settings_apply_to_runtime(disabled_page_diagnosis_via_api):
    settings = config.get_settings()
    assert settings.page_diagnosis_enabled is False
    assert settings.page_diagnosis_llm_enabled is False
    assert settings.page_diagnosis_screenshot_enabled is False
    assert settings.page_diagnosis_llm_timeout_seconds == 12
    assert settings.page_diagnosis_rule_confidence_skip_llm == 0.88


@pytest.mark.asyncio
async def test_page_diagnosis_settings_disable_skips_reporter(disabled_page_diagnosis_via_api):
    settings = config.get_settings()
    reporter = CrawlFailureReporter(settings, tenant_id="default")
    result = await reporter.report(
        platform="douyin",
        operation="crawl_keyword",
        skill_result={"status": "failed", "error": "需要登录"},
        snapshot_provider=None,
    )
    assert result is None


@pytest.fixture
def remote_api_client(monkeypatch, tmp_path):
    settings = _build_test_settings(tmp_path)
    settings.desktop_mode = False
    settings.database_url = "postgresql://user:pass@localhost/huoke"
    _install_api_settings(monkeypatch, settings)
    _install_fake_login_store(monkeypatch)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_settings, None)


def test_page_diagnosis_settings_forbidden_on_remote_db(remote_api_client):
    put_resp = remote_api_client.put(
        "/api/settings/page-diagnosis",
        headers=API_HEADERS,
        json={"enabled": True},
    )
    assert put_resp.status_code == 403
    assert "页面诊断设置" in put_resp.json()["detail"]

    get_resp = remote_api_client.get("/api/settings/page-diagnosis", headers=API_HEADERS)
    assert get_resp.status_code == 200
    assert get_resp.json()["enabled"] is True
