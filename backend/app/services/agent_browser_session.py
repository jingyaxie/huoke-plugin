from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    BROWSER_RENDER_EPOCH,
    _MAIN_PAGE_HOLDER,
    bind_main_page_guards,
    headless_for_platform,
    launch_browser,
    new_browser_context,
    open_tenant_page,
    register_main_page,
    uses_native_system_chrome,
    warmup_douyin,
)
from app.core.config import Settings
from app.platforms.registry import get_session_store
from app.services.agent_network_capture import NetworkCapture


@dataclass
class AgentBrowserSession:
    session_id: str
    tenant_id: str
    platform: str
    settings: Settings
    account_id: str = "default"
    headless: bool | None = None
    skip_home_warmup: bool = False
    stable_mode: bool = False
    owner_job_id: str | None = None
    bootstrapped: bool = False
    agent_profile_id: str | None = None
    active_skill_id: str | None = None
    _playwright: Playwright | None = field(default=None, repr=False)
    _browser: Browser | None = field(default=None, repr=False)
    _context: BrowserContext | None = field(default=None, repr=False)
    _page: Page | None = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    network_capture: NetworkCapture = field(default_factory=NetworkCapture, repr=False)

    @property
    def is_started(self) -> bool:
        return self._page is not None and self._is_alive()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器会话未启动")
        return self._page

    def _is_alive(self) -> bool:
        if self._page is None:
            return False
        try:
            if self._page.is_closed():
                return False
            browser = getattr(self._context, "browser", None)
            if browser is not None and not browser.is_connected():
                return False
            return True
        except Exception:
            return False

    async def _force_cleanup_unlocked(self) -> None:
        """关闭旧 Chrome/Playwright，避免重建会话时多窗口闪烁。"""
        self.network_capture.detach()
        with contextlib.suppress(Exception):
            if self._context is not None:
                await self._context.close()
            elif self._browser is not None:
                await self._browser.close()
        with contextlib.suppress(Exception):
            if self._playwright is not None:
                await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    async def _discard_dead_browser(self) -> None:
        """浏览器已被用户/系统关掉，清引用以便下次 ensure_started 重建。"""
        async with self._lock:
            await self._force_cleanup_unlocked()
            if self.stable_mode:
                self.bootstrapped = False

    async def ensure_started(self) -> Page:
        if self._page is not None and not self._is_alive():
            await self._discard_dead_browser()
        if self._page is not None:
            return self.page
        timeout = float(self.settings.agent_browser_start_timeout_seconds)
        await asyncio.wait_for(self.start(), timeout=timeout)
        return self.page

    async def start(self) -> None:
        async with self._lock:
            if self._page is not None and self._is_alive():
                return
            if self._context is not None:
                holder: dict[str, Page | None] = getattr(self._context, _MAIN_PAGE_HOLDER, None) or {}
                main = holder.get("page")
                if main is not None and not main.is_closed():
                    self._page = main
                    self.network_capture.attach(self._page)
                    return
                for candidate in self._context.pages:
                    if not candidate.is_closed():
                        self._page = candidate
                        self.network_capture.attach(self._page)
                        register_main_page(self._context, self._page)
                        return
            if self._browser is not None or self._context is not None or self._playwright is not None:
                await self._force_cleanup_unlocked()
            store = get_session_store(self.settings, self.platform)
            self._playwright = await async_playwright().start()
            self._browser, self._context, self._page = await open_tenant_page(
                self._playwright,
                self.settings,
                self.platform,
                self.tenant_id,
                store,
                headless=self.headless,
                account_id=self.account_id,
            )
            self.network_capture.attach(self._page)
            resolved_headless = headless_for_platform(
                self.settings,
                self.platform,
                self.headless,
            )
            if not resolved_headless and not self.stable_mode:
                await self._warmup_visible_home()
            if self._context is not None and self._page is not None:
                await bind_main_page_guards(
                    self._context,
                    self._page,
                    browser=self._browser,
                    settings=self.settings,
                    headless=resolved_headless,
                )
            if self.stable_mode:
                return

    async def bootstrap_once(self) -> dict[str, str]:
        """稳定基座：单窗口、只引导航一次。"""
        from app.services.browser_workbench import bootstrap_stable_page

        self.stable_mode = True
        self.skip_home_warmup = True
        return await bootstrap_stable_page(self)

    async def _warmup_visible_home(self) -> None:
        """有头模式启动后导航到平台首页，避免停留在 about:blank。"""
        if self._page is None or self.skip_home_warmup:
            return
        resolved_headless = headless_for_platform(self.settings, self.platform, self.headless)
        if resolved_headless:
            return
        try:
            if self.platform == "douyin":
                await warmup_douyin(self._page, self.settings, tenant_id=self.tenant_id)
            elif self.platform == "xiaohongshu":
                await self._page.goto(
                    self.settings.xhs_home_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            elif self.platform == "kuaishou":
                await self._page.goto(
                    self.settings.kuaishou_home_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
        except Exception:
            pass

    async def close(self) -> None:
        async with self._lock:
            self.network_capture.detach()
            if self._context is not None:
                try:
                    store = get_session_store(self.settings, self.platform)
                    if self.platform == "xiaohongshu" and self._page is not None:
                        from app.platforms.xiaohongshu.ui_helpers import save_login_if_authenticated

                        await save_login_if_authenticated(
                            self._page,
                            self._context,
                            store,
                            self.tenant_id,
                            self.account_id,
                        )
                    else:
                        await store.save_from_context(self.tenant_id, self._context, self.account_id)
                except Exception:
                    pass
                await self._context.close()
                self._context = None
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            self._page = None

    async def page_info(self) -> dict[str, str | None]:
        page = self.page
        return {
            "url": page.url,
            "title": await page.title(),
        }

    def tab_audit_events(self) -> list[dict]:
        from app.services.popup_tab_audit import get_tab_audit_events

        return get_tab_audit_events(self._context)

    async def capture_storage_state(self) -> dict:
        if self._context is None:
            raise RuntimeError("浏览器上下文未启动")
        try:
            return await self._context.storage_state()
        except Exception:
            # lf-zt 等埋点域 tab 被关后，Playwright 遍历 origins 会 goto 失败。
            cookies = await self._context.cookies()
            return {"cookies": cookies, "origins": []}

    async def restore_from_checkpoint(self, storage_state: dict, url: str | None = None) -> None:
        async with self._lock:
            if self._playwright is None:
                raise RuntimeError("浏览器未启动")
            if self._page is not None:
                await self._page.close()
                self._page = None
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._browser is None:
                resolved_headless = headless_for_platform(self.settings, self.platform, self.headless)
                self._browser = await launch_browser(self._playwright, self.settings, headless=resolved_headless)
            resolved_headless = headless_for_platform(self.settings, self.platform, self.headless)
            self._context = await new_browser_context(
                self._browser,
                self.settings,
                state=storage_state,
                tenant_id=self.tenant_id,
                visible=not resolved_headless,
            )
            self._page = await self._context.new_page()
            self.network_capture.clear()
            self.network_capture.attach(self._page)
            from app.core.antibot import bind_main_page_guards

            resolved_headless = headless_for_platform(
                self.settings,
                self.platform,
                self.headless,
            )
            if url and url not in {"", "about:blank"}:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=90000)
            elif not resolved_headless:
                await self._warmup_visible_home()
            await bind_main_page_guards(
                self._context,
                self._page,
                browser=self._browser,
                settings=self.settings,
                headless=resolved_headless,
            )


class AgentSessionManager:
    _instance: AgentSessionManager | None = None

    def __init__(self) -> None:
        self._sessions: dict[str, AgentBrowserSession] = {}
        self._manager_lock = asyncio.Lock()
        self._browser_render_epoch = 0

    async def sync_browser_render_epoch(self) -> None:
        """渲染参数变更后自动关闭旧 Chrome，下次任务用新启动参数。"""
        if self._browser_render_epoch == BROWSER_RENDER_EPOCH:
            return
        await self.shutdown_all()
        self._browser_render_epoch = BROWSER_RENDER_EPOCH

    @classmethod
    def get_instance(cls) -> AgentSessionManager:
        if cls._instance is None:
            cls._instance = AgentSessionManager()
        return cls._instance

    def find_reusable_stable(
        self,
        tenant_id: str,
        platform: str,
        account_id: str,
        owner_job_id: str | None = None,
    ) -> AgentBrowserSession | None:
        for session in self._sessions.values():
            if (
                session.stable_mode
                and session._is_alive()
                and session.tenant_id == tenant_id
                and session.platform == platform
                and session.account_id == account_id
                and (owner_job_id is None or session.owner_job_id == owner_job_id)
            ):
                return session
        return None

    async def _close_siblings(
        self,
        tenant_id: str,
        platform: str,
        account_id: str,
    ) -> None:
        """有头模式新建会话前关闭同租户/平台/账号的旧会话，避免 Chrome 窗口堆积。"""
        async with self._manager_lock:
            has_stable = any(
                item.tenant_id == tenant_id
                and item.platform == platform
                and item.account_id == account_id
                and item.stable_mode
                for item in self._sessions.values()
            )
            if has_stable:
                return
            stale_ids = [
                sid
                for sid, item in self._sessions.items()
                if item.tenant_id == tenant_id
                and item.platform == platform
                and item.account_id == account_id
                and not item.stable_mode
            ]
        for sid in stale_ids:
            await self.close(sid)

    async def create(
        self,
        tenant_id: str,
        platform: str,
        settings: Settings,
        *,
        account_id: str = "default",
        headless: bool | None = None,
        auto_start: bool = True,
        owner_job_id: str | None = None,
    ) -> AgentBrowserSession:
        await self.sync_browser_render_epoch()
        resolved_headless = headless_for_platform(settings, platform, headless)
        if not resolved_headless and not uses_native_system_chrome(settings, headless=False):
            await self._close_siblings(tenant_id, platform, account_id)
        session_id = str(uuid.uuid4())
        session = AgentBrowserSession(
            session_id=session_id,
            tenant_id=tenant_id,
            platform=platform,
            settings=settings,
            account_id=account_id,
            headless=headless,
            owner_job_id=owner_job_id,
        )
        if auto_start:
            await session.start()
        async with self._manager_lock:
            self._sessions[session_id] = session
        return session

    async def create_stable(
        self,
        tenant_id: str,
        platform: str,
        settings: Settings,
        *,
        account_id: str = "default",
        headless: bool | None = None,
        owner_job_id: str | None = None,
    ) -> AgentBrowserSession:
        """创建或复用稳定浏览器基座（长会话任务场景）。"""
        existing = self.find_reusable_stable(tenant_id, platform, account_id, owner_job_id=owner_job_id)
        if existing is not None:
            return existing
        async with self._manager_lock:
            dead_ids = [
                sid
                for sid, item in self._sessions.items()
                if item.stable_mode
                and item.tenant_id == tenant_id
                and item.platform == platform
                and item.account_id == account_id
                and (owner_job_id is None or item.owner_job_id == owner_job_id)
                and not item._is_alive()
            ]
        for sid in dead_ids:
            await self.close(sid)
        session = await self.create(
            tenant_id,
            platform,
            settings,
            account_id=account_id,
            headless=headless,
            auto_start=False,
            owner_job_id=owner_job_id,
        )
        session.stable_mode = True
        session.skip_home_warmup = True
        await session.bootstrap_once()
        return session

    def get(self, session_id: str) -> AgentBrowserSession | None:
        return self._sessions.get(session_id)

    async def close(self, session_id: str) -> bool:
        async with self._manager_lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await session.close()
        return True

    async def shutdown_all(self) -> None:
        async with self._manager_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await session.close()
