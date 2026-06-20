"""共享 API 测试 fixtures。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.services.agent_async_job_service import AgentAsyncJobService
from app.services.task_brief_service import TaskBrief
from tests.helpers import API_HEADERS

__all__ = ["API_HEADERS", "api_client", "capture_submit", "flow_client", "mock_task_brief"]


def mock_task_brief_factory():
    async def mock_brief(message, **kwargs):
        from app.services.task_brief_service import _finalize_brief

        return _finalize_brief(
            TaskBrief(
                title="深圳餐饮线索",
                brief_md="# 深圳餐饮线索\n\n## 目标\n抓取关键词评论线索",
                platform=str(kwargs.get("platform") or "douyin"),
                keyword="团餐配送",
                region="深圳",
                goals={"target_leads": 50, "comment_days": 3, "video_publish_days": 7},
                reasoning="mock brief for automated flow test",
                confidence=0.9,
                llm_available=True,
                llm_fallback=False,
            )
        )

    return mock_brief


@pytest.fixture
def mock_task_brief(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_job_plan_service.generate_task_brief",
        mock_task_brief_factory(),
    )


def _build_test_settings(tmp_path) -> Settings:
    storage = tmp_path / "storage"
    return Settings(
        storage_root=storage,
        deepseek_api_key="test-deepseek-key",
        tenant_auth_enabled=False,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )


def _install_api_settings(monkeypatch, settings: Settings):
    from app.core import config as config_module

    config_module.get_settings.cache_clear()

    def _get_settings():
        return settings

    monkeypatch.setattr("app.core.config.get_settings", _get_settings)
    monkeypatch.setattr("app.api.deps.get_settings", _get_settings)
    monkeypatch.setattr("app.api.settings_routes.get_settings", _get_settings)
    monkeypatch.setattr("app.api.agent_routes.get_settings", _get_settings)
    app.dependency_overrides[get_settings] = _get_settings


def _install_fake_login_store(monkeypatch):
    class FakeStore:
        def login_status(self, tenant_id: str, account_id: str = "default"):
            return {"status": "ready", "nickname": "测试号", "cookie_ready": True}

    monkeypatch.setattr(
        "app.services.external_task_preflight_service.get_session_store",
        lambda _settings, _platform: FakeStore(),
    )


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    settings = _build_test_settings(tmp_path)
    _install_api_settings(monkeypatch, settings)
    _install_fake_login_store(monkeypatch)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_settings, None)
    AgentAsyncJobService._instance = None


@pytest.fixture
def flow_client(monkeypatch, tmp_path, mock_task_brief):
    """真实任务创建/编排/执行链路；mock LLM 简报与 Supervisor 执行。"""
    AgentAsyncJobService._instance = None
    settings = _build_test_settings(tmp_path)
    _install_api_settings(monkeypatch, settings)
    _install_fake_login_store(monkeypatch)

    async def mock_supervisor_run(self, **kwargs):
        job_result = dict(kwargs.get("job_result") or {})
        cycles = list(job_result.get("supervisor_cycles") or [])
        cycles.append(
            {
                "cycle": len(cycles) + 1,
                "action": "crawl_keyword",
                "reasoning": "自动化测试模拟抓取",
                "ok": True,
                "result_summary": "dry-run 抓取完成",
            }
        )
        return {
            **job_result,
            "status": "completed",
            "summary": "flow test completed",
            "supervisor_cycles": cycles,
        }

    monkeypatch.setattr(
        "app.services.agent_async_job_service.TaskSupervisorService.run",
        mock_supervisor_run,
    )

    svc = AgentAsyncJobService.get(settings)
    monkeypatch.setattr(svc, "_ensure_workers", lambda: None)

    with TestClient(app) as test_client:
        yield test_client, settings, svc

    app.dependency_overrides.pop(get_settings, None)
    AgentAsyncJobService._instance = None


@pytest.fixture
def capture_submit(monkeypatch):
    captured: dict = {}

    async def fake_submit_async(self, **kwargs):
        captured.update(kwargs)
        from datetime import datetime, timezone

        from app.services.agent_async_job_service import AgentAsyncJob

        now = datetime.now(timezone.utc)
        return AgentAsyncJob(
            job_id="job-test-e2e",
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
    return captured
