from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_run_controller import AgentRunController
from app.services.agent_service import AgentService


@pytest.mark.asyncio
async def test_cancel_run_marks_interrupted_and_closes_browser():
    controller = AgentRunController.get()
    run_id = "test-run-cancel-001"
    await controller.register(run_id)

    settings = MagicMock()
    settings.default_tenant_id = "default"
    agent = AgentService(settings, "default", "douyin", account_id="default")

    run = MagicMock()
    run.status = "active"
    run.browser_session_id = "browser-1"
    agent.run_store.get = MagicMock(return_value=run)
    agent.run_store.save = MagicMock()

    session = MagicMock()
    session.close = AsyncMock()
    agent.session_manager.get = MagicMock(return_value=session)

    assert await agent.cancel_run(run_id) is True
    assert run.status == "interrupted"
    agent.run_store.save.assert_called_once()
    session.close.assert_awaited_once()
    assert controller.is_cancelled(run_id)

    await controller.clear(run_id)


@pytest.mark.asyncio
async def test_ensure_browser_with_cancel_aborts_when_flag_set():
    controller = AgentRunController.get()
    run_id = "test-run-cancel-002"
    await controller.register(run_id)
    await controller.cancel(run_id)

    settings = MagicMock()
    agent = AgentService(settings, "default", "douyin", account_id="default")
    session = MagicMock()
    session.is_started = False

    page = await agent._ensure_browser_with_cancel(session, run_id)
    assert page is None
    session.ensure_started.assert_not_called()

    await controller.clear(run_id)
