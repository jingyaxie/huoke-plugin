from __future__ import annotations

import asyncio
import base64
import time

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import apply_stealth, context_kwargs, launch_browser
from app.core.config import Settings
from app.platforms.kuaishou.constants import HOME_URL, PLATFORM, REQUIRED_LOGIN_COOKIES
from app.platforms.kuaishou.session import KuaishouSessionStore
from app.platforms.qr_login_parsers import kuaishou_status_from_scan, normalize_image_base64
from app.platforms.qr_login_store import QrLoginSession
from app.platforms.session_store import PlatformSessionStore

DEFAULT_TTL_SECONDS = 120
VALIDITY_HINT = "快手二维码约 2 分钟内有效，过期后请重新获取"


class KuaishouQrLoginTool:
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

    async def open_runtime(self) -> dict:
        import os

        playwright = await async_playwright().start()
        # 快手登录弹框在纯 headless 下常不渲染二维码，优先使用 有头浏览器。
        headless = False if os.environ.get("DISPLAY") else True
        browser = await launch_browser(playwright, self.settings, headless=headless)
        context = await browser.new_context(**context_kwargs(self.settings))
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return {
            "playwright": playwright,
            "browser": browser,
            "context": context,
            "page": page,
            "last_scan": None,
        }

    def _attach_listener(self, runtime: dict) -> None:
        page: Page = runtime["page"]

        async def on_response(resp) -> None:
            url = resp.url
            try:
                if "qr/start" in url:
                    body = await resp.json()
                    if isinstance(body, dict) and body.get("result") == 1:
                        runtime["qr_payload"] = body
                if "qr/scanResult" in url:
                    runtime["last_scan"] = await resp.json()
            except Exception:
                return

        runtime["listener"] = on_response
        page.on("response", on_response)

    async def _open_login_modal(self, page: Page) -> None:
        for selector in ("text=登录", "span:has-text('登录')", "div:has-text('登录')"):
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=3000)
                    break
            except Exception:
                continue
        await page.wait_for_timeout(1500)
        for selector in ("text=立即登录", "button:has-text('立即登录')", "div:has-text('立即登录')"):
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=3000)
                    return
            except Exception:
                continue
        raise RuntimeError("未能打开快手登录弹框，请稍后重试")

    async def fetch_qr(self, session: QrLoginSession, runtime: dict) -> None:
        page: Page = runtime["page"]
        runtime["qr_payload"] = None
        self._attach_listener(runtime)
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        await self._open_login_modal(page)
        for _ in range(30):
            if runtime.get("qr_payload"):
                break
            await page.wait_for_timeout(500)

        qr_payload = runtime.get("qr_payload")
        if not qr_payload:
            dom = await page.evaluate(
                """() => {
                    const img = document.querySelector('img[src^="data:image"]');
                    if (!img || !img.src) return null;
                    return { src: img.src, width: img.width, height: img.height };
                }"""
            )
            if isinstance(dom, dict) and dom.get("src"):
                session.qr_image_base64 = str(dom["src"])
            if not session.qr_image_base64:
                element = page.locator('img[src^="data:image"]').first
                if await element.count() > 0:
                    png = await element.screenshot(type="png")
                    session.qr_image_base64 = "data:image/png;base64," + base64.b64encode(png).decode("ascii")

        if qr_payload:
            session.qr_id = str(qr_payload.get("qrLoginToken") or "")
            session.poll_token = str(qr_payload.get("qrLoginSignature") or "")
            session.qr_scan_url = qr_payload.get("qrUrl") or None
            raw_img = qr_payload.get("imageData")
            if raw_img:
                session.qr_image_base64 = normalize_image_base64(str(raw_img))
            expire_time = qr_payload.get("expireTime")
            if expire_time:
                session.expires_at = float(expire_time) / 1000
            runtime["sid"] = str(qr_payload.get("sid") or "kuaishou.server.webday7")

        if not session.qr_image_base64 and not session.qr_scan_url:
            raise RuntimeError("未能获取快手登录二维码，请使用 有头浏览器登录（server-login）（server-login）")

        if not session.expires_at:
            session.expires_at = time.time() + DEFAULT_TTL_SECONDS
        session.validity_hint = VALIDITY_HINT
        session.status = "pending"
        session.message = "请使用快手 App 扫码"

    async def poll_once(self, session: QrLoginSession, runtime: dict) -> None:
        if session.expires_at and time.time() >= session.expires_at:
            session.status = "expired"
            session.message = "二维码已过期，请重新获取"
            return

        context: BrowserContext = runtime["context"]
        last_scan = runtime.get("last_scan")
        if isinstance(last_scan, dict):
            status, message = kuaishou_status_from_scan(last_scan)
            if status != "pending":
                session.status = status
            if message:
                session.message = message

        cookies = await context.cookies()
        cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
        if cookie_names & REQUIRED_LOGIN_COOKIES:
            session.status = "confirmed"
            session.message = "登录成功"
            await self.store.save_from_context(self.tenant_id, context, self.account_id)

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
                    if session.status in {"confirmed", "expired", "error"}:
                        break
                    await asyncio.sleep(2)
            finally:
                await self.cleanup_runtime(runtime)
                session.runtime = {}

        session.poll_task = asyncio.create_task(_loop())
