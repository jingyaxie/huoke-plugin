from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.core.config import Settings
from app.platforms.constants import BINDABLE_PLATFORMS
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.kuaishou.crawler import KuaishouCrawler
from app.platforms.registry import get_session_store
from app.platforms.xiaohongshu.constants import REQUIRED_LOGIN_COOKIES as XHS_REQUIRED_LOGIN_COOKIES
from app.platforms.xiaohongshu.crawler import XhsCrawler
from app.platforms.xiaohongshu.ui_helpers import save_login_if_authenticated

_INTERACTIVE_CRAWLERS: dict[str, type] = {
    "douyin": DouyinCrawler,
    "xiaohongshu": XhsCrawler,
    "kuaishou": KuaishouCrawler,
}

logger = logging.getLogger(__name__)

_SESSION_STOP_TASK_TIMEOUT_S = 8.0
_SESSION_CLEANUP_TIMEOUT_S = 12.0


async def _cleanup_session_payload(session: dict[str, Any]) -> None:
    context = session.get("context")
    browser = session.get("browser")
    playwright = session.get("playwright")
    with suppress(Exception):
        if context is not None:
            await context.close()
    with suppress(Exception):
        if browser is not None:
            await browser.close()
    with suppress(Exception):
        if playwright is not None:
            await playwright.stop()


async def stop_interactive_session(
    platform: str,
    tenant_id: str,
    account_id: str,
) -> bool:
    """停止指定平台的交互登录任务并释放 本机浏览器窗口。"""
    crawler_cls = _INTERACTIVE_CRAWLERS.get(platform.strip().lower())
    if crawler_cls is None:
        return False

    key = crawler_cls._session_key(tenant_id, account_id)
    session = crawler_cls._interactive_sessions.pop(key, None)
    task = crawler_cls._interactive_tasks.pop(key, None)

    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            try:
                await asyncio.wait_for(task, timeout=_SESSION_STOP_TASK_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning(
                    "interactive login task stop timed out platform=%s tenant=%s account=%s",
                    platform,
                    tenant_id,
                    account_id,
                )

    if session is not None:
        try:
            await asyncio.wait_for(
                _cleanup_session_payload(session),
                timeout=_SESSION_CLEANUP_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "interactive login browser cleanup timed out platform=%s tenant=%s account=%s",
                platform,
                tenant_id,
                account_id,
            )
        return True
    return task is not None


async def stop_all_interactive_sessions(
    tenant_id: str,
    account_id: str,
    *,
    except_platform: str | None = None,
) -> list[str]:
    """关闭同租户账号下所有（或其它平台）交互登录，避免 浏览器仍显示上一平台页面。"""
    stopped: list[str] = []
    for platform in BINDABLE_PLATFORMS:
        if except_platform and platform == except_platform.strip().lower():
            continue
        if await stop_interactive_session(platform, tenant_id, account_id):
            stopped.append(platform)
    return stopped


async def restart_interactive_login_for_platform(
    tenant_id: str,
    account_id: str,
    platform: str,
) -> list[str]:
    """切换平台登录前：先关掉其它平台，再关掉本平台旧窗口以便重新打开。"""
    stopped = await stop_all_interactive_sessions(tenant_id, account_id)
    platform = platform.strip().lower()
    if await stop_interactive_session(platform, tenant_id, account_id):
        if platform not in stopped:
            stopped.append(platform)
    return stopped


async def try_persist_interactive_login(
    platform: str,
    tenant_id: str,
    account_id: str,
    settings: Settings,
) -> bool:
    """若交互登录窗口仍开着，尝试从浏览器上下文落盘 Cookie（供 login-status 轮询）。"""
    platform = platform.strip().lower()
    crawler_cls = _INTERACTIVE_CRAWLERS.get(platform)
    if crawler_cls is None:
        return False

    session = crawler_cls.get_interactive_session(platform, tenant_id, account_id)
    if not session:
        return False

    context = session.get("context")
    page = session.get("page")
    if context is None or page is None:
        return False
    try:
        if page.is_closed():
            return False
    except Exception:
        return False

    if platform == "douyin":
        crawler = DouyinCrawler(settings, tenant_id, account_id=account_id)
        return await crawler.try_persist_from_session(context, page)

    if platform == "xiaohongshu":
        cookies = await context.cookies()
        cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
        if not ("web_session" in cookie_names and (cookie_names & XHS_REQUIRED_LOGIN_COOKIES)):
            return False
        store = get_session_store(settings, platform)
        result = await save_login_if_authenticated(
            page, context, store, tenant_id, account_id
        )
        return bool(result.get("saved"))

    return False


async def probe_interactive_login(
    platform: str,
    tenant_id: str,
    account_id: str,
) -> dict:
    """返回交互登录窗口实时探测信息，便于排查「已登录但未落盘」。"""
    platform = platform.strip().lower()
    crawler_cls = _INTERACTIVE_CRAWLERS.get(platform)
    if crawler_cls is None:
        return {"interactive_active": False}

    session = crawler_cls.get_interactive_session(platform, tenant_id, account_id)
    if not session:
        return {"interactive_active": False}

    page = session.get("page")
    context = session.get("context")
    probe: dict = {"interactive_active": True}
    if page is None or context is None:
        probe["probe_error"] = "session_missing_page_or_context"
        return probe

    try:
        probe["page_url"] = page.url
        if platform == "douyin":
            from app.platforms.douyin.human_guards import (
                _detect_login_wall,
                _live_cookie_names,
                is_blocked_douyin_host,
                is_browser_blocked_page,
            )

            blocked, block_reason = await is_browser_blocked_page(page)
            probe["blocked_host"] = blocked or is_blocked_douyin_host(page.url or "")
            probe["block_reason"] = block_reason
            probe["login_wall_visible"] = await _detect_login_wall(page)
            probe["live_cookie_names"] = sorted(await _live_cookie_names(page))[:40]
        else:
            cookies = await context.cookies()
            probe["live_cookie_names"] = sorted(
                {cookie.get("name") for cookie in cookies if cookie.get("name")}
            )[:40]
    except Exception as exc:
        probe["probe_error"] = str(exc)
    return probe
