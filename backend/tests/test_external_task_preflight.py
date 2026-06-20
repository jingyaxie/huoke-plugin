from __future__ import annotations

import pytest

from app.schemas.external_task import (
    ExternalTaskCorrelation,
    ExternalTaskCreateRequest,
    ExternalTaskCrawl,
    ExternalTaskEvaluation,
    ExternalTaskOutreach,
    ExternalTaskScope,
)
from app.services.external_task_preflight_service import run_external_task_preflight


@pytest.fixture
def settings():
    from app.core.config import Settings

    return Settings(
        deepseek_api_key="test-deepseek-key",
        openai_api_key=None,
    )


@pytest.mark.asyncio
async def test_preflight_keyword_auto_ready(settings, monkeypatch):
    login_status = {"status": "ready", "nickname": "测试号"}

    class FakeStore:
        def login_status(self, tenant_id: str, account_id: str = "default"):
            return login_status

    monkeypatch.setattr(
        "app.services.external_task_preflight_service.get_session_store",
        lambda _settings, _platform: FakeStore(),
    )

    request = ExternalTaskCreateRequest(
        intent="keyword_auto",
        name="淋浴房获客",
        platform="douyin",
        scope=ExternalTaskScope(keyword="淋浴房", target_count=50, comment_days=3),
        evaluation=ExternalTaskEvaluation(accept_description="有淋浴房购买或安装意向"),
        correlation=ExternalTaskCorrelation(external_task_id="preflight-1"),
        agent_strategy="skill-flow-douyin",
    )
    result = await run_external_task_preflight(
        request,
        settings=settings,
        tenant_id="default",
        account_id="default",
    )
    assert result.ready is True
    assert result.blocking_count == 0
    check_ids = {item.id for item in result.checks}
    assert {"runtime", "login", "llm", "orchestration", "evaluation"}.issubset(check_ids)
    actions = [str(row.get("action") or "") for row in (result.orchestration.steps if result.orchestration else [])]
    assert "evaluate_leads" in actions
    assert "crawl_keyword" in actions


@pytest.mark.asyncio
async def test_preflight_blocks_when_not_logged_in(settings, monkeypatch):
    class FakeStore:
        def login_status(self, tenant_id: str, account_id: str = "default"):
            return {"status": "missing", "message": "请先登录"}

    monkeypatch.setattr(
        "app.services.external_task_preflight_service.get_session_store",
        lambda _settings, _platform: FakeStore(),
    )

    request = ExternalTaskCreateRequest(
        intent="keyword_auto",
        name="测试",
        platform="douyin",
        scope=ExternalTaskScope(keyword="健身房", target_count=20),
        correlation=ExternalTaskCorrelation(external_task_id="preflight-2"),
    )
    result = await run_external_task_preflight(
        request,
        settings=settings,
        tenant_id="default",
        account_id="default",
    )
    assert result.ready is False
    login_check = next(item for item in result.checks if item.id == "login")
    assert login_check.status == "error"
    assert login_check.blocking is True


@pytest.mark.asyncio
async def test_preflight_blocks_without_llm_key(settings, monkeypatch):
    from app.core.config import Settings

    bare_settings = Settings(deepseek_api_key=None, openai_api_key=None)

    class FakeStore:
        def login_status(self, tenant_id: str, account_id: str = "default"):
            return {"status": "ready"}

    monkeypatch.setattr(
        "app.services.external_task_preflight_service.get_session_store",
        lambda _settings, _platform: FakeStore(),
    )

    request = ExternalTaskCreateRequest(
        intent="keyword_auto",
        name="测试",
        platform="douyin",
        scope=ExternalTaskScope(keyword="健身房", target_count=20),
        correlation=ExternalTaskCorrelation(external_task_id="preflight-3"),
    )
    result = await run_external_task_preflight(
        request,
        settings=bare_settings,
        tenant_id="default",
        account_id="default",
    )
    assert result.ready is False
    llm_check = next(item for item in result.checks if item.id == "llm")
    assert llm_check.status == "error"


@pytest.mark.asyncio
async def test_preflight_scope_missing_keyword(settings):
    request = ExternalTaskCreateRequest(
        intent="keyword_auto",
        name="缺关键词",
        platform="douyin",
        scope=ExternalTaskScope(target_count=20),
        correlation=ExternalTaskCorrelation(external_task_id="preflight-4"),
    )
    result = await run_external_task_preflight(
        request,
        settings=settings,
        tenant_id="default",
        account_id="default",
    )
    assert result.ready is False
    scope_check = next(item for item in result.checks if item.id == "scope")
    assert scope_check.status == "error"


@pytest.mark.asyncio
async def test_preflight_manual_plan_includes_evaluate(settings, monkeypatch):
    class FakeStore:
        def login_status(self, tenant_id: str, account_id: str = "default"):
            return {"status": "ready"}

    monkeypatch.setattr(
        "app.services.external_task_preflight_service.get_session_store",
        lambda _settings, _platform: FakeStore(),
    )

    request = ExternalTaskCreateRequest(
        intent="single_video",
        name="单视频",
        platform="douyin",
        scope=ExternalTaskScope(
            input_url="https://www.douyin.com/video/123",
            comment_days=3,
        ),
        evaluation=ExternalTaskEvaluation(accept_description="潜在客户"),
        correlation=ExternalTaskCorrelation(external_task_id="preflight-5"),
    )
    result = await run_external_task_preflight(
        request,
        settings=settings,
        tenant_id="default",
        account_id="default",
    )
    orch_check = next(item for item in result.checks if item.id == "orchestration")
    assert orch_check.status == "ok"
    actions = [str(row.get("action") or "") for row in (result.orchestration.steps if result.orchestration else [])]
    assert "evaluate_leads" in actions
    assert "crawl_content_url" in actions
