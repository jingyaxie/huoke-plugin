from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.kuaishou.constants import PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.profile import KuaishouProfileTool
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class KuaishouDmTool(KuaishouJsApiTool):
    """快手私信工具（主页打开 IM 面板 + 轻量 UI 发送）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = KuaishouProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def send_message(
        self,
        *,
        user_id: str,
        message: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not user_id:
            raise ValueError("缺少 user_id")
        if not (message or "").strip():
            raise ValueError("发送私信需要 message")

        headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=headless,
            account_id=self.account_id,
        ) as (_, page):
            result = await self._send_on_page(page, user_id=user_id, message=message, username=username)

        output = (
            self.settings.report_output_dir
            / f"dm_{self.platform}_{self.tenant_id}_{user_id[:12]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result

    async def _send_on_page(self, page, *, user_id: str, message: str, username: str) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        profile_url = await self._profile.open_profile(page, user_id)

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "username": username,
            "user_id": user_id,
            "profile_url": profile_url,
            "page_url": page.url,
            "capture_method": "profile_dm_panel",
            "message": await self._send_dm_on_profile(page, message),
        }

    async def _send_dm_on_profile(self, page, message: str) -> dict:
        selectors = (
            'button:has-text("发私信")',
            'button:has-text("私信")',
            'a:has-text("发私信")',
            '[class*="message"] button',
        )
        dm = None
        for selector in selectors:
            loc = page.locator(selector).first
            if await loc.count():
                dm = loc
                break
        if dm is None:
            return {"ok": False, "error": "dm_button_not_found"}

        await dm.click()
        await page.wait_for_timeout(2500)

        inp = page.locator('textarea, div[contenteditable="true"], input[placeholder*="消息"]').first
        if not await inp.count():
            return {
                "ok": False,
                "error": "dm_input_not_found",
                "hint": "私信面板未打开，可能受隐私/互关限制",
            }

        await inp.click()
        await inp.fill(message)
        await page.wait_for_timeout(400)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        body_text = await page.evaluate("() => document.body.innerText || ''")
        visible = message in body_text
        return {
            "ok": visible,
            "method": "profile_dm_panel",
            "verified_in_page": visible,
            "text_preview": message[:80],
        }
