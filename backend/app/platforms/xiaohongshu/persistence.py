from __future__ import annotations

import logging
import shutil
from typing import Any

from playwright.async_api import async_playwright

from app.core.antibot import launch_persistent_context, persistent_profile_enabled
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import PLATFORM
from app.platforms.xiaohongshu.ui_helpers import ensure_logged_in_user
from app.platforms.xiaohongshu.session_meta import mark_session_expired, record_authenticated_snapshot

logger = logging.getLogger(__name__)


async def rebake_persistent_profile(
    settings: Settings,
    store: PlatformSessionStore,
    tenant_id: str,
    account_id: str = "default",
) -> dict[str, Any]:
    """网页扫码登录在临时浏览器完成，需把 storage_state 烘焙进 Playwright 持久化 Profile。"""
    if not persistent_profile_enabled(settings, PLATFORM):
        return {"synced": False, "reason": "persistent_profile_disabled"}

    state = store.load(tenant_id, account_id)
    if not state or not state.get("cookies"):
        return {"synced": False, "reason": "missing_storage_state"}

    profile_dir = store.profile_dir_for(tenant_id, account_id)
    if profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)

    explore = settings.xhs_explore_url or settings.xhs_home_url
    playwright = await async_playwright().start()
    try:
        context = await launch_persistent_context(
            playwright,
            settings,
            PLATFORM,
            tenant_id,
            store,
            headless=True,
            account_id=account_id,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(explore, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)
        login = await ensure_logged_in_user(page)
        if not login.get("ok"):
            mark_session_expired(
                store,
                tenant_id,
                account_id,
                reason="guest_after_rebake",
                detail=str(login.get("error") or ""),
            )
            return {
                "synced": False,
                "reason": "guest_after_rebake",
                "error": login.get("error"),
                "profile_dir": str(profile_dir),
            }
        path = await store.save_from_context(tenant_id, context, account_id)
        await record_authenticated_snapshot(store, tenant_id, account_id, page, user_id=login.get("user_id"))
        await context.close()
        return {
            "synced": True,
            "path": str(path),
            "profile_dir": str(profile_dir),
            "user_id": login.get("user_id"),
        }
    except Exception as exc:
        logger.warning("xhs rebake_persistent_profile failed: %s", exc)
        return {"synced": False, "reason": "rebake_failed", "error": str(exc)}
    finally:
        await playwright.stop()


async def verify_live_session(
    settings: Settings,
    store: PlatformSessionStore,
    tenant_id: str,
    account_id: str = "default",
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """在线校验登录态；可选 refresh 时写回 storage_state / session_meta / Profile。"""
    from app.core.antibot import headless_for_platform

    state = store.load(tenant_id, account_id)
    if not state or not state.get("cookies"):
        return {
            "live_ok": False,
            "auth_status": "missing",
            "message": "未找到登录态文件",
            "needs_relogin": True,
        }

    explore = settings.xhs_explore_url or settings.xhs_home_url
    playwright = await async_playwright().start()
    context = None
    try:
        context = await launch_persistent_context(
            playwright,
            settings,
            PLATFORM,
            tenant_id,
            store,
            headless=headless_for_platform(settings, PLATFORM, True),
            account_id=account_id,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(explore, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)
        login = await ensure_logged_in_user(page)
        if login.get("ok"):
            refreshed = False
            if refresh:
                await store.save_from_context(tenant_id, context, account_id)
                refreshed = True
            await record_authenticated_snapshot(
                store, tenant_id, account_id, page, user_id=login.get("user_id")
            )
            status = store.login_status(tenant_id, account_id)
            return {
                "live_ok": True,
                "refreshed": refreshed,
                "auth_status": status.get("auth_status"),
                "status": status.get("status"),
                "message": "登录态有效，已更新持久化" if refreshed else "登录态有效",
                "needs_relogin": False,
                "user_id": login.get("user_id"),
                **{
                    k: status[k]
                    for k in ("cookie_expires_at", "cookie_expires_in_seconds", "session_meta")
                    if k in status
                },
            }

        mark_session_expired(
            store,
            tenant_id,
            account_id,
            reason="live_verify_failed",
            detail=str(login.get("error") or ""),
        )
        status = store.login_status(tenant_id, account_id)
        return {
            "live_ok": False,
            "refreshed": False,
            "auth_status": status.get("auth_status"),
            "status": status.get("status"),
            "message": status.get("message") or "登录态已失效，请重新扫码登录",
            "needs_relogin": True,
            "error": login.get("error"),
        }
    except Exception as exc:
        logger.warning("xhs verify_live_session failed: %s", exc)
        mark_session_expired(
            store,
            tenant_id,
            account_id,
            reason="live_verify_failed",
            detail=str(exc),
        )
        status = store.login_status(tenant_id, account_id)
        return {
            "live_ok": False,
            "refreshed": False,
            "auth_status": status.get("auth_status"),
            "status": status.get("status"),
            "message": f"在线校验失败：{exc}",
            "needs_relogin": True,
            "error": str(exc),
        }
    finally:
        if context is not None:
            await context.close()
        await playwright.stop()
