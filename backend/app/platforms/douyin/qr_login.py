from __future__ import annotations

import asyncio
import time

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import apply_stealth, context_kwargs, launch_browser
from app.core.config import Settings
from app.platforms.douyin.session import DouyinSessionStore, REQUIRED_LOGIN_COOKIES
from app.platforms.qr_login_parsers import douyin_status_from_check, normalize_image_base64
from app.platforms.qr_login_store import QrLoginSession
from app.platforms.session_store import PlatformSessionStore

PLATFORM = "douyin"
DEFAULT_TTL_SECONDS = 180
VALIDITY_HINT = "抖音二维码约 3 分钟内有效，过期后请重新获取"


class DouyinQrLoginTool:
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

    async def open_runtime(self) -> dict:
        playwright = await async_playwright().start()
        browser = await launch_browser(playwright, self.settings, headless=True)
        context = await browser.new_context(**context_kwargs(self.settings))
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return {
            "playwright": playwright,
            "browser": browser,
            "context": context,
            "page": page,
            "last_check": None,
        }

    def _attach_listener(self, runtime: dict) -> None:
        page: Page = runtime["page"]

        async def on_response(resp) -> None:
            url = resp.url
            try:
                if "get_qrcode" in url:
                    body = await resp.json()
                    data = body.get("data") if isinstance(body, dict) else None
                    if isinstance(data, dict) and data.get("token"):
                        runtime["qr_payload"] = data
                if "check_qrconnect" in url or "check_qrcode" in url:
                    runtime["last_check"] = await resp.json()
            except Exception:
                return

        runtime["listener"] = on_response
        page.on("response", on_response)

    async def fetch_qr(self, session: QrLoginSession, runtime: dict) -> None:
        page: Page = runtime["page"]
        runtime["qr_payload"] = None
        self._attach_listener(runtime)
        await page.goto(self.settings.douyin_home_url, wait_until="domcontentloaded", timeout=30000)
        for selector in ("text=登录", "p:has-text('登录')", "div:has-text('登录')"):
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=2000)
                    break
            except Exception:
                continue
        for _ in range(30):
            if runtime.get("qr_payload"):
                break
            await page.wait_for_timeout(500)
        qr_payload = runtime.get("qr_payload")

        if not qr_payload:
            raise RuntimeError("未能获取抖音登录二维码，请稍后重试或使用 有头浏览器登录（server-login）")

        session.poll_token = str(qr_payload.get("token") or "")
        session.qr_scan_url = qr_payload.get("qrcode_index_url") or None
        session.qr_image_base64 = normalize_image_base64(qr_payload.get("qrcode"))
        expire_time = qr_payload.get("expire_time")
        session.expires_at = float(expire_time) if expire_time else time.time() + DEFAULT_TTL_SECONDS
        session.validity_hint = VALIDITY_HINT
        session.status = "pending"
        session.message = "请使用抖音 App 扫码"

    async def poll_once(self, session: QrLoginSession, runtime: dict) -> None:
        if session.expires_at and time.time() >= session.expires_at:
            session.status = "expired"
            session.message = "二维码已过期，请重新获取"
            return

        page: Page = runtime["page"]
        context: BrowserContext = runtime["context"]
        last_check = runtime.get("last_check")
        if last_check:
            status, message = douyin_status_from_check(last_check)
            session.status = status
            if message:
                session.message = message

        cookies = await context.cookies()
        cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
        if cookie_names & REQUIRED_LOGIN_COOKIES:
            session.status = "confirmed"
            session.message = "登录成功"
            await self.store.save_from_context(self.tenant_id, context, self.account_id)
            return

        if session.status in {"pending", "scanned"}:
            await page.wait_for_timeout(1500)
            last_check = runtime.get("last_check")
            if last_check:
                status, message = douyin_status_from_check(last_check)
                session.status = status
                if message:
                    session.message = message

    async def cleanup_runtime(self, runtime: dict | None) -> None:
        if not runtime:
            return
        page: Page | None = runtime.get("page")
        listener = runtime.get("listener")
        if page is not None and listener is not None:
            try:
                page.remove_listener("response", listener)
            except Exception:
                pass
        context: BrowserContext | None = runtime.get("context")
        browser: Browser | None = runtime.get("browser")
        playwright: Playwright | None = runtime.get("playwright")
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    async def start_poll_loop(self, session: QrLoginSession) -> None:
        runtime = session.runtime

        async def _loop() -> None:
            try:
                while session.status in {"pending", "scanned"}:
                    await self.poll_once(session, runtime)
                    if session.status == "confirmed":
                        break
                    if session.status in {"expired", "error"}:
                        break
                    await asyncio.sleep(2)
            finally:
                await self.cleanup_runtime(runtime)
                session.runtime = {}

        session.poll_task = asyncio.create_task(_loop())
