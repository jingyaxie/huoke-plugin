from __future__ import annotations

from unittest.mock import MagicMock

from app.core.config import Settings
from app.services.agent_browser_session import AgentBrowserSession, AgentSessionManager


def test_is_started_false_when_page_closed():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s1",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
    )
    page = MagicMock()
    page.is_closed.return_value = True
    session._page = page
    assert session.is_started is False
    assert session._is_alive() is False


def test_is_started_true_when_page_open():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s2",
        tenant_id="default",
        platform="douyin",
        settings=settings,
    )
    page = MagicMock()
    page.is_closed.return_value = False
    session._page = page
    session._context = MagicMock(browser=MagicMock(is_connected=lambda: True))
    assert session.is_started is True


def test_find_reusable_stable_scopes_by_owner_job_id():
    settings = Settings()
    manager = AgentSessionManager()
    session_a = AgentBrowserSession(
        session_id="s-a",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
        owner_job_id="job-a",
    )
    session_b = AgentBrowserSession(
        session_id="s-b",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
        owner_job_id="job-b",
    )
    for session in (session_a, session_b):
        page = MagicMock()
        page.is_closed.return_value = False
        session._page = page
        session._context = MagicMock(browser=MagicMock(is_connected=lambda: True))
        manager._sessions[session.session_id] = session

    assert manager.find_reusable_stable("default", "douyin", "default", owner_job_id="job-a") is session_a
    assert manager.find_reusable_stable("default", "douyin", "default", owner_job_id="job-b") is session_b
    assert manager.find_reusable_stable("default", "douyin", "default", owner_job_id="job-c") is None
