from __future__ import annotations

import asyncio

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    apply_stealth,
    context_kwargs,
    headless_for_platform,
    human_delay,
    launch_browser,
    open_tenant_page,
    require_login,
)
from app.core.config import Settings
from app.platforms.kuaishou.constants import HOME_URL, PLATFORM, REQUIRED_LOGIN_COOKIES
from app.platforms.kuaishou.session import KuaishouSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.schemas.crawl import CrawlItem
from app.services.playwright_pool import PlaywrightPool


class KuaishouCrawler:
    _interactive_sessions: dict[str, dict] = {}
    _interactive_tasks: dict[str, asyncio.Task] = {}

    platform = PLATFORM

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.store = store or KuaishouSessionStore(settings)
        self.pool = PlaywrightPool.get()

    @classmethod
    def _session_key(cls, tenant_id: str, account_id: str = "default") -> str:
        return f"{PLATFORM}:{tenant_id}:{account_id}"

    def _context_kwargs(self) -> dict:
        return context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))

    async def _launch_standalone_context(
        self, headless: bool | None = None
    ) -> tuple[Playwright, Browser, BrowserContext, Page]:
        playwright = await async_playwright().start()
        browser = await launch_browser(
            playwright,
            self.settings,
            headless=headless_for_platform(self.settings, PLATFORM, headless),
        )
        context = await browser.new_context(**self._context_kwargs())
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return playwright, browser, context, page

    async def login_and_save_cookies(self, show_browser: bool = True) -> None:
        playwright, browser, context, page = await self._launch_standalone_context(headless=not show_browser)
        try:
            await page.goto(self.settings.kuaishou_home_url, wait_until="domcontentloaded", timeout=120000)
            if not show_browser:
                raise RuntimeError("快手 Cookie 登录需要可见浏览器，请设置 KUAISHOU_HEADLESS=false")
            for _ in range(60):
                cookies = await context.cookies()
                cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
                if cookie_names & REQUIRED_LOGIN_COOKIES:
                    await self.store.save_from_context(self.tenant_id, context, self.account_id)
                    return
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
            await self.store.save_from_context(self.tenant_id, context, self.account_id)
            raise RuntimeError("未检测到快手登录态，请在浏览器中完成扫码/验证后重试。")
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    async def start_interactive_login_session(self) -> dict:
        key = self._session_key(self.tenant_id, self.account_id)
        task = KuaishouCrawler._interactive_tasks.get(key)
        if task and not task.done() and key in KuaishouCrawler._interactive_sessions:
            return {
                "status": "running",
                "message": "该账号的快手登录窗口已在运行",
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "platform": PLATFORM,
            }
        KuaishouCrawler._interactive_tasks[key] = asyncio.create_task(self._run_interactive_login_session())
        return {
            "status": "started",
            "message": "快手登录窗口已启动",
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "platform": PLATFORM,
        }

    @classmethod
    def get_interactive_session(cls, platform: str, tenant_id: str, account_id: str = "default") -> dict | None:
        if platform != PLATFORM:
            return None
        session = cls._interactive_sessions.get(cls._session_key(tenant_id, account_id))
        if not session:
            return None
        page = session.get("page")
        if page is None:
            return None
        try:
            if page.is_closed():
                return None
        except Exception:
            return None
        return session

    def login_status(self, tenant_id: str) -> dict:
        return self.store.login_status(tenant_id, account_id=self.account_id)

    async def _run_interactive_login_session(self) -> None:
        key = self._session_key(self.tenant_id, self.account_id)
        playwright = await async_playwright().start()
        browser = None
        context = None
        try:
            browser, context, page = await open_tenant_page(
                playwright,
                self.settings,
                PLATFORM,
                self.tenant_id,
                self.store,
                headless=False,
                account_id=self.account_id,
            )
            KuaishouCrawler._interactive_sessions[key] = {
                "platform": PLATFORM,
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
            }
            await page.goto(self.settings.kuaishou_home_url, wait_until="domcontentloaded", timeout=120000)
            for _ in range(180):
                cookies = await context.cookies()
                cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
                if cookie_names & REQUIRED_LOGIN_COOKIES:
                    await self.store.save_from_context(self.tenant_id, context, self.account_id)
                    await page.goto(self.settings.kuaishou_home_url, wait_until="domcontentloaded", timeout=120000)
                    break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
            while True:
                await page.wait_for_timeout(1000)
        finally:
            KuaishouCrawler._interactive_sessions.pop(key, None)
            KuaishouCrawler._interactive_tasks.pop(key, None)
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
            await playwright.stop()

    async def fetch_hot(self, limit: int = 100) -> list[CrawlItem]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        async with self.pool.tenant_context(
            PLATFORM, self.tenant_id, self.store, self.settings, account_id=self.account_id
        ) as (_, page):
            await page.goto(self.settings.kuaishou_home_url, wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            links = await page.locator('a[href*="/short-video/"], a[href*="/video/"]').evaluate_all(
                "els => els.map(e => ({ href: e.href, text: (e.innerText || '').trim() }))"
            )
            results: list[CrawlItem] = []
            seen: set[str] = set()
            for link in links:
                href = link.get("href") or ""
                if href in seen:
                    continue
                seen.add(href)
                text = (link.get("text") or "").strip()
                title = text if len(text) >= 2 else f"快手视频 {len(results) + 1}"
                results.append(
                    CrawlItem(
                        platform=PLATFORM,
                        rank=len(results) + 1,
                        title=title[:500],
                        external_id=href.rsplit("/", 1)[-1][:64] or str(len(results)),
                        video_url=href,
                        raw_data={"href": href, "platform": PLATFORM, "tenant_id": self.tenant_id},
                    )
                )
                if len(results) >= limit:
                    break
            return results
