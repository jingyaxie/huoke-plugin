from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import suppress
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import (
    _seed_storage_from_state,
    apply_stealth,
    context_kwargs,
    headless_for_platform,
    human_delay,
    launch_browser,
    open_tenant_page,
    require_login,
    uses_native_system_chrome,
)
from app.core.config import Settings
from app.platforms.douyin.session import (
    DouyinSessionStore,
    REQUIRED_LOGIN_COOKIES,
    USER_LOGIN_MARKERS,
    _cookie_value,
)
from app.platforms.session_store import PlatformSessionStore
from app.schemas.crawl import CrawlItem
from app.services.playwright_pool import PlaywrightPool
from app.platforms.douyin.human_guards import (
    _detect_login_wall,
    _live_cookie_names,
    is_blocked_douyin_host,
    is_browser_blocked_page,
)
from app.utils.parsers import parse_count, parse_datetime


PLATFORM = "douyin"
logger = logging.getLogger(__name__)


class DouyinCrawler:
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
        self.store = store or DouyinSessionStore(settings)
        self.pool = PlaywrightPool.get()

    @classmethod
    def _session_key(cls, tenant_id: str, account_id: str = "default") -> str:
        return f"{cls.platform}:{tenant_id}:{account_id}"

    def _context_kwargs(self) -> dict:
        return context_kwargs(self.settings, self.store.load(self.tenant_id, self.account_id))

    async def _launch_standalone_context(
        self, headless: bool | None = None
    ) -> tuple[Playwright, Browser, BrowserContext, Page]:
        playwright = await async_playwright().start()
        browser = await launch_browser(
            playwright,
            self.settings,
            headless=headless_for_platform(self.settings, self.platform, headless),
        )
        context = await browser.new_context(**self._context_kwargs())
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return playwright, browser, context, page

    @property
    def entry_url(self) -> str:
        return self.settings.douyin_hot_url

    async def login_and_save_cookies(self, show_browser: bool = True) -> None:
        playwright, browser, context, page = await self._launch_standalone_context(headless=not show_browser)
        try:
            await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
            if not show_browser:
                raise RuntimeError("Cookie login requires an interactive browser. Set DOUYIN_HEADLESS=false first.")
            for _ in range(60):
                cookies = await context.cookies()
                cookie_names = {cookie.get("name") for cookie in cookies if cookie.get("name")}
                if cookie_names & REQUIRED_LOGIN_COOKIES:
                    await self.store.save_from_context(self.tenant_id, context, self.account_id)
                    return
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
            await self.store.save_from_context(self.tenant_id, context, self.account_id)
            raise RuntimeError("未检测到有效登录态，请在浏览器里完成扫码/验证后重试。")
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    @staticmethod
    def _session_page_alive(session: dict | None) -> bool:
        if not session:
            return False
        page = session.get("page")
        if page is None:
            return False
        try:
            return not page.is_closed()
        except Exception:
            return False

    async def start_interactive_login_session(self, *, restore: bool = True) -> dict:
        key = self._session_key(self.tenant_id, self.account_id)
        task = DouyinCrawler._interactive_tasks.get(key)
        session = DouyinCrawler._interactive_sessions.get(key)
        if task and not task.done() and session and self._session_page_alive(session):
            return {
                "status": "running",
                "message": "该账号的服务器登录窗口已在运行",
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "platform": self.platform,
            }
        if task and not task.done():
            from app.platforms.interactive_login import stop_interactive_session

            await stop_interactive_session(self.platform, self.tenant_id, self.account_id)
        task = asyncio.create_task(self._run_interactive_login_session(restore=restore))
        task.add_done_callback(
            lambda done: logger.error(
                "douyin interactive login task failed tenant=%s account=%s",
                self.tenant_id,
                self.account_id,
                exc_info=done.exception() if not done.cancelled() else False,
            )
            if not done.cancelled() and done.exception() is not None
            else None
        )
        DouyinCrawler._interactive_tasks[key] = task
        return {
            "status": "started",
            "message": "服务器登录窗口已启动",
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "platform": self.platform,
        }

    @classmethod
    def get_interactive_session(cls, platform: str, tenant_id: str, account_id: str = "default") -> dict | None:
        if platform != cls.platform:
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

    async def _collect_login_cookie_names(self, context: BrowserContext) -> set[str]:
        names: set[str] = set()
        urls = (
            self.settings.douyin_home_url,
            "https://www.douyin.com",
            "https://douyin.com",
        )
        batches = [await context.cookies()]
        for url in urls:
            batches.append(await context.cookies(url))
        for batch in batches:
            names |= {cookie.get("name") for cookie in batch if cookie.get("name")}
        return names

    async def _live_uid_tt(self, context: BrowserContext, page: Page) -> str | None:
        urls = (
            self.settings.douyin_home_url,
            "https://www.douyin.com",
            "https://douyin.com",
            page.url or "",
        )
        for url in urls:
            if not url:
                continue
            with suppress(Exception):
                for cookie in await context.cookies(url):
                    if cookie.get("name") == "uid_tt":
                        value = str(cookie.get("value") or "").strip()
                        if value:
                            return value
        with suppress(Exception):
            for cookie in await context.cookies():
                if cookie.get("name") == "uid_tt":
                    value = str(cookie.get("value") or "").strip()
                    if value:
                        return value
        return None

    async def try_persist_from_session(self, context: BrowserContext, page: Page) -> bool:
        return await self._persist_session_if_ready(context, page)

    async def _ensure_on_douyin_home(self, page: Page) -> None:
        url = (page.url or "").strip()
        blocked, _ = await is_browser_blocked_page(page)
        if blocked or is_blocked_douyin_host(url) or "douyin.com" not in url:
            await page.goto(self.settings.douyin_home_url, wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")

    async def _persist_session_if_ready(self, context: BrowserContext, page: Page) -> bool:
        cookie_names = await self._collect_login_cookie_names(context)
        live_names = await _live_cookie_names(page)
        cookie_names |= live_names
        has_session_cookies = bool(cookie_names & REQUIRED_LOGIN_COOKIES) or bool(
            cookie_names & USER_LOGIN_MARKERS
        )
        login_wall = await _detect_login_wall(page)
        blocked, block_reason = await is_browser_blocked_page(page)
        if blocked:
            logger.warning(
                "douyin interactive login blocked page tenant=%s account=%s reason=%s url=%s",
                self.tenant_id,
                self.account_id,
                block_reason,
                page.url,
            )
            return False
        if not has_session_cookies:
            return False
        key = self._session_key(self.tenant_id, self.account_id)
        session = DouyinCrawler._interactive_sessions.get(key) or {}
        now = time.monotonic()
        last_persist = float(session.get("_last_persist_monotonic") or 0)
        stored_uid = _cookie_value(self.store.load(self.tenant_id, self.account_id), "uid_tt")
        live_uid = await self._live_uid_tt(context, page)
        identity_changed = bool(live_uid and stored_uid and live_uid != stored_uid)
        state_path = self.store.path_for(self.tenant_id, self.account_id)
        if self.settings.desktop_mode:
            # 桌面端 Profile 自持久化；JSON 仅作离线状态缓存。
            export_cache = identity_changed or not state_path.exists() or now - last_persist > 300
            if export_cache:
                await self.store.save_from_context(self.tenant_id, context, self.account_id)
                session["_last_persist_monotonic"] = now
                DouyinCrawler._interactive_sessions[key] = session
                logger.info(
                    "douyin login cache exported tenant=%s account=%s identity_changed=%s live_uid=%s",
                    self.tenant_id,
                    self.account_id,
                    identity_changed,
                    live_uid or "",
                )
            return True
        if not identity_changed and now - last_persist < 60:
            return True
        await self.store.save_from_context(self.tenant_id, context, self.account_id)
        session["_last_persist_monotonic"] = now
        DouyinCrawler._interactive_sessions[key] = session
        logger.info(
            "douyin login persisted tenant=%s account=%s cookies=%s login_wall=%s identity_changed=%s live_uid=%s",
            self.tenant_id,
            self.account_id,
            sorted(cookie_names)[:12],
            login_wall,
            identity_changed,
            live_uid or "",
        )
        return True

    async def _restore_login_page(
        self,
        context: BrowserContext,
        page: Page,
        *,
        restore: bool = True,
    ) -> None:
        """open_tenant_page 在 restore 时已注入 storage_state；此处仅导航到首页并兜底补灌。"""
        home_url = self.settings.douyin_home_url
        if not restore:
            url = (page.url or "").strip()
            blocked, _ = await is_browser_blocked_page(page)
            if blocked or is_blocked_douyin_host(url) or "douyin.com" not in url:
                await page.goto(home_url, wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            return
        state = self.store.load(self.tenant_id, self.account_id)
        url = (page.url or "").strip()
        blocked, _ = await is_browser_blocked_page(page)
        if blocked or is_blocked_douyin_host(url) or "douyin.com" not in url:
            await page.goto(home_url, wait_until="domcontentloaded", timeout=120000)
        if state and self.store.is_ready(state) and await _detect_login_wall(page):
            await _seed_storage_from_state(context, state, replace=True)
            await page.goto(home_url, wait_until="domcontentloaded", timeout=120000)
        await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")

    async def _run_interactive_login_session(self, *, restore: bool = True) -> None:
        key = self._session_key(self.tenant_id, self.account_id)
        playwright = await async_playwright().start()
        browser = None
        context = None
        try:
            browser, context, page = await open_tenant_page(
                playwright,
                self.settings,
                self.platform,
                self.tenant_id,
                self.store,
                headless=False,
                account_id=self.account_id,
                use_storage_state=restore,
            )
            DouyinCrawler._interactive_sessions[key] = {
                "platform": self.platform,
                "tenant_id": self.tenant_id,
                "account_id": self.account_id,
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
            }
            await self._restore_login_page(context, page, restore=restore)
            while True:
                if await self._persist_session_if_ready(context, page):
                    await page.wait_for_timeout(30000)
                else:
                    await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
        finally:
            DouyinCrawler._interactive_sessions.pop(key, None)
            DouyinCrawler._interactive_tasks.pop(key, None)
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
            await playwright.stop()

    async def fetch_hot(self, limit: int = 100) -> list[CrawlItem]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        async with self.pool.tenant_context(
            self.platform, self.tenant_id, self.store, self.settings, account_id=self.account_id
        ) as (_, page):
            await page.goto(self.entry_url, wait_until="domcontentloaded", timeout=120000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            items = await self._extract_from_page(page, limit=limit)
            return items[:limit]

    async def _extract_from_page(self, page: Page, limit: int) -> list[CrawlItem]:
        cards = page.locator("a")
        count = await cards.count()
        results: list[CrawlItem] = []
        seen_video_ids: set[str] = set()
        for index in range(min(count, 500)):
            node = cards.nth(index)
            href = await node.get_attribute("href")
            text = " ".join((await node.inner_text(timeout=1000) or "").split())
            if not text or len(text) < 4:
                continue
            href_text = href or ""
            if "/video/" not in href_text and "/note/" not in href_text:
                continue
            video_id = self._extract_video_id(href)
            if video_id and video_id in seen_video_ids:
                continue
            parsed = self._parse_hot_card_text(text)
            title = parsed.get("title") or ""
            if len(title) < 2:
                continue
            if video_id:
                seen_video_ids.add(video_id)
            item = CrawlItem(
                platform=self.platform,
                rank=len(results) + 1,
                title=title,
                author_name=parsed.get("author_name") or self._guess_author(text),
                external_id=video_id,
                video_url=self._to_absolute_url(page.url, href),
                like_count=parse_count(parsed.get("like_count_text") or self._match_count(text, ("点赞", "赞"))),
                comment_count=parse_count(self._match_count(text, ("评论", "评"))),
                share_count=parse_count(self._match_count(text, ("分享", "转"))),
                publish_time=parse_datetime(parsed.get("publish_time_text") or self._match_publish_time(text)),
                raw_data={
                    "text": text,
                    "href": href,
                    "index": index,
                    "tenant_id": self.tenant_id,
                    "platform": self.platform,
                },
            )
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def _parse_hot_card_text(self, text: str) -> dict:
        clean = " ".join(text.split())
        clean = re.sub(r"^\d{1,2}:\d{2}\s*", "", clean)

        like_count_text: str | None = None
        like_match = re.match(r"^([0-9]+(?:\.[0-9]+)?[万亿]?)\s+", clean)
        if like_match:
            like_count_text = like_match.group(1)
            clean = clean[like_match.end() :].strip()

        author_name: str | None = None
        author_match = re.search(r"@([^\s·•|]+)", clean)
        if author_match:
            candidate = author_match.group(1).strip()
            if not self._is_invalid_author_name(candidate):
                author_name = candidate

        publish_time_text: str | None = None
        time_match = re.search(r"(\d+[天周月年]前|\d{1,2}月\d{1,2}日)", clean)
        if time_match:
            publish_time_text = time_match.group(1)

        if author_match:
            title = clean[: author_match.start()].strip()
        else:
            title = re.sub(r"(\d+[天周月年]前|\d{1,2}月\d{1,2}日)$", "", clean).strip()

        title = re.sub(r"[·•|]\s*$", "", title).strip()
        return {
            "title": title,
            "author_name": author_name,
            "like_count_text": like_count_text,
            "publish_time_text": publish_time_text,
        }

    def _extract_video_id(self, href: str | None) -> str | None:
        if not href:
            return None
        match = re.search(r"/video/(\d+)", href)
        return match.group(1) if match else None

    def _to_absolute_url(self, page_url: str, href: str | None) -> str | None:
        if not href:
            return None
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            from urllib.parse import urljoin

            return urljoin(page_url, href)
        return None

    def _guess_author(self, text: str) -> str | None:
        parts = [part for part in re.split(r"[|•·/\n]", text) if part.strip()]
        if len(parts) >= 2:
            candidate = parts[1].strip()
            if self._is_invalid_author_name(candidate):
                return None
            return candidate
        return None

    def _match_count(self, text: str, labels: tuple[str, ...]) -> str | None:
        for label in labels:
            match = re.search(label + r"[:：]?\s*([0-9.]+[万亿]?)", text)
            if match:
                return match.group(1)
        return None

    def _match_publish_time(self, text: str) -> str | None:
        match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)", text)
        return match.group(1) if match else None

    def _is_invalid_author_name(self, value: str | None) -> bool:
        if not value:
            return True
        text = value.strip()
        if not text:
            return True
        if re.fullmatch(r"\d{1,2}月\d{1,2}日", text):
            return True
        if re.fullmatch(r"\d+[天周月年]前", text):
            return True
        if len(text) > 30:
            return True
        if re.search(r"[#·•|]", text):
            return True
        return False
