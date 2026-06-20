from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import time

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.antibot import apply_stealth, context_kwargs, launch_browser
from app.core.config import Settings
from app.platforms.qr_login_parsers import normalize_image_base64, xhs_status_from_poll
from app.platforms.qr_login_store import QrLoginSession
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import REQUIRED_LOGIN_COOKIES
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.platforms.xiaohongshu.ui_helpers import activate_session, save_login_if_authenticated

DEFAULT_TTL_SECONDS = 180
VALIDITY_HINT = "小红书二维码约 3 分钟内有效，过期后请重新获取"


class XhsQrLoginTool:
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
        self.store = store or XhsSessionStore(settings)

    @staticmethod
    def _web_session_value(cookies: list) -> str | None:
        for cookie in cookies:
            if isinstance(cookie, dict) and cookie.get("name") == "web_session":
                value = str(cookie.get("value") or "").strip()
                return value or None
        return None

    async def open_runtime(self) -> dict:
        playwright = await async_playwright().start()
        headless = False if os.environ.get("DISPLAY") else True
        browser = await launch_browser(playwright, self.settings, headless=headless)
        context = await browser.new_context(**context_kwargs(self.settings))
        await apply_stealth(context, self.settings, tenant_id=self.tenant_id)
        page = await context.new_page()
        return {"playwright": playwright, "browser": browser, "context": context, "page": page}

    async def _ensure_qr_login_tab(self, page: Page) -> None:
        for selector in (
            "text=扫码登录",
            "span:has-text('扫码登录')",
            "div:has-text('扫码登录')",
            "text=二维码登录",
        ):
            try:
                loc = page.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=2000)
                    await page.wait_for_timeout(600)
                    return
            except Exception:
                continue

    async def _fill_qr_image_from_dom(self, page: Page, session: QrLoginSession) -> bool:
        if session.qr_image_base64:
            return True

        dom = await page.evaluate(
            """() => {
                const imgs = Array.from(document.querySelectorAll('img[src^="data:image"]'));
                const hit = imgs.find((img) => (img.width || img.clientWidth) >= 80) || imgs[0];
                if (!hit || !hit.src) return null;
                return { src: hit.src, width: hit.width || hit.clientWidth, height: hit.height || hit.clientHeight };
            }"""
        )
        if isinstance(dom, dict) and dom.get("src"):
            session.qr_image_base64 = normalize_image_base64(str(dom["src"]))
            return True

        for selector in (
            'img[src^="data:image"]',
            ".login-container img",
            ".reds-modal img",
            "canvas",
        ):
            try:
                loc = page.locator(selector).first
                if await loc.count() == 0:
                    continue
                png = await loc.screenshot(type="png")
                if png:
                    session.qr_image_base64 = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _generate_qr_image_base64(scan_url: str) -> str | None:
        if not scan_url:
            return None
        try:
            import qrcode
        except ImportError:
            return None
        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(scan_url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return normalize_image_base64(base64.b64encode(buf.getvalue()).decode("ascii"))

    async def fetch_qr(self, session: QrLoginSession, runtime: dict) -> None:
        page: Page = runtime["page"]
        create_body: dict | None = None

        async def on_response(resp) -> None:
            nonlocal create_body
            if "login/qrcode/create" not in resp.url:
                return
            try:
                body = await resp.json()
                if body.get("data", {}).get("qr_id"):
                    create_body = body
            except Exception:
                return

        context: BrowserContext = runtime["context"]
        await context.clear_cookies()
        page.on("response", on_response)
        try:
            warmup = self.settings.xhs_explore_url or self.settings.xhs_home_url
            await page.goto(warmup, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1200)
            await self._ensure_qr_login_tab(page)
            for _ in range(30):
                if create_body:
                    break
                await page.wait_for_timeout(500)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        if not create_body:
            raise RuntimeError("未能获取小红书登录二维码，请稍后重试或使用 有头浏览器登录（server-login）")

        data = create_body.get("data") or {}
        session.qr_id = str(data.get("qr_id") or "")
        session.qr_code = str(data.get("code") or "")
        session.qr_scan_url = data.get("url") or None
        session.qr_image_url = data.get("qr_url") or data.get("image") or None

        img_base64 = data.get("qr_code") or data.get("image_base64")
        if img_base64:
            session.qr_image_base64 = normalize_image_base64(str(img_base64))

        for _ in range(12):
            if await self._fill_qr_image_from_dom(page, session):
                break
            await page.wait_for_timeout(500)

        if not session.qr_image_base64 and session.qr_scan_url:
            session.qr_image_base64 = self._generate_qr_image_base64(session.qr_scan_url)

        if not session.qr_image_base64:
            raise RuntimeError("未能渲染小红书登录二维码图片，请刷新后重试")

        expires_at = None
        scan_url = session.qr_scan_url or ""
        match = re.search(r"timestamp=(\d+)", scan_url)
        if match:
            expires_at = int(match.group(1)) / 1000 + DEFAULT_TTL_SECONDS
        session.expires_at = expires_at or (time.time() + DEFAULT_TTL_SECONDS)
        session.validity_hint = VALIDITY_HINT
        session.status = "pending"
        session.message = "请使用小红书 App 扫码"
        runtime["baseline_web_session"] = self._web_session_value(await context.cookies())

    async def poll_once(self, session: QrLoginSession, runtime: dict) -> None:
        if session.expires_at and time.time() >= session.expires_at:
            session.status = "expired"
            session.message = "二维码已过期，请重新获取"
            return

        page: Page = runtime["page"]
        context: BrowserContext = runtime["context"]
        if not session.qr_id or not session.qr_code:
            session.status = "error"
            session.message = "二维码会话缺少 qr_id/code"
            return

        status_body = await page.evaluate(
            """async ({ qrId, code }) => {
                const u = 'https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/status?qr_id='
                    + encodeURIComponent(qrId) + '&code=' + encodeURIComponent(code);
                const r = await fetch(u, { credentials: 'include' });
                return await r.json();
            }""",
            {"qrId": session.qr_id, "code": session.qr_code},
        )
        status, message = xhs_status_from_poll(status_body if isinstance(status_body, dict) else {})
        if status != "confirmed":
            session.status = status
            if message:
                session.message = message
            return

        session.status = "scanned"
        session.message = "已扫码，正在写入登录态…"
        baseline_web_session = runtime.get("baseline_web_session")
        for _ in range(12):
            await activate_session(page)
            cookies = await context.cookies()
            current_web_session = self._web_session_value(cookies)
            cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
            session_changed = bool(
                current_web_session
                and current_web_session != baseline_web_session
                and "web_session" in cookie_names
                and (cookie_names & REQUIRED_LOGIN_COOKIES)
            )
            if session_changed:
                from app.platforms.xiaohongshu.ui_helpers import fetch_user_me

                user_me = await fetch_user_me(page)
                if user_me.get("guest") is False:
                    saved = await save_login_if_authenticated(
                        page,
                        context,
                        self.store,
                        self.tenant_id,
                        self.account_id,
                        rebake_profile=True,
                    )
                    if saved.get("saved"):
                        session.status = "confirmed"
                        session.message = "登录成功"
                        return
                    session.status = "error"
                    sync = saved.get("profile_sync") if isinstance(saved.get("profile_sync"), dict) else {}
                    session.message = (
                        saved.get("error")
                        or sync.get("error")
                        or "扫码成功，但登录态未能写入持久化存储，请重试或打开有头浏览器登录"
                    )
                    return
            await page.wait_for_timeout(500)

        session.status = "error"
        session.message = "扫码已成功，但账号仍处于游客态或未激活，请刷新二维码重试"

    async def cleanup_runtime(self, runtime: dict | None) -> None:
        if not runtime:
            return
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
