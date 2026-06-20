from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from app.core.config import Settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.browser_workbench import (
    bootstrap_stable_page,
    is_douyin_home_like,
    normalize_url,
    should_skip_stable_goto,
)


def test_normalize_url_strips_trailing_slash():
    assert normalize_url("https://www.Douyin.com/jingxuan/") == normalize_url(
        "https://www.douyin.com/jingxuan"
    )


def test_is_douyin_home_like():
    assert is_douyin_home_like("https://www.douyin.com/")
    assert is_douyin_home_like("https://www.douyin.com/jingxuan")
    assert not is_douyin_home_like("https://www.douyin.com/search/kw")


def test_should_skip_same_url_in_stable_mode():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s1",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
    )
    page = MagicMock()
    page.url = "https://www.douyin.com/jingxuan"
    session._page = page
    skip, reason = should_skip_stable_goto(session, "https://www.douyin.com/jingxuan/")
    assert skip is True
    assert reason == "same_url"


def test_should_skip_home_when_already_on_home():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s2",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
    )
    page = MagicMock()
    page.url = "https://www.douyin.com/jingxuan?recommend=1"
    session._page = page
    skip, reason = should_skip_stable_goto(session, settings.douyin_home_url)
    assert skip is True
    assert reason == "already_on_home"


def test_should_not_skip_when_not_stable_mode():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s3",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=False,
    )
    page = MagicMock()
    page.url = "https://www.douyin.com/jingxuan"
    session._page = page
    skip, _ = should_skip_stable_goto(session, settings.douyin_home_url)
    assert skip is False


@pytest.mark.asyncio
async def test_bootstrap_stable_page_reuses_existing_douyin_url():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s5",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
    )
    page = MagicMock()
    page.url = "https://www.douyin.com/search/团餐配送"
    page.title = AsyncMock(return_value="抖音搜索")
    session._page = page
    session.ensure_started = AsyncMock(return_value=page)  # type: ignore[method-assign]

    result = await bootstrap_stable_page(session)
    assert result["status"] == "reused_on_page"
    page.goto.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_stable_page_rejects_so_landing():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s6",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
    )
    page = MagicMock()
    page.url = "https://so-landing.douyin.com/"
    page.title = AsyncMock(return_value="404 Not Found")
    session._page = page
    session.ensure_started = AsyncMock(return_value=page)  # type: ignore[method-assign]

    from app.platforms.douyin.human_guards import HumanBrowseGuardError

    with pytest.raises(HumanBrowseGuardError, match="so-landing"):
        await bootstrap_stable_page(session)


@pytest.mark.asyncio
async def test_bootstrap_stable_page_reuses_bootstrapped_session():
    settings = Settings()
    session = AgentBrowserSession(
        session_id="s4",
        tenant_id="default",
        platform="douyin",
        settings=settings,
        stable_mode=True,
    )
    page = MagicMock()
    page.url = "https://www.douyin.com/jingxuan"
    page.title = AsyncMock(return_value="抖音")
    session._page = page
    session.bootstrapped = True
    session.ensure_started = AsyncMock(return_value=page)  # type: ignore[method-assign]
    type(session).is_started = PropertyMock(return_value=True)

    result = await bootstrap_stable_page(session)
    assert result["status"] == "reused"
    page.goto.assert_not_called()
    session.ensure_started.assert_not_called()
