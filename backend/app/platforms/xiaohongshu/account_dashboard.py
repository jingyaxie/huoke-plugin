from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.account_dashboard_parsers import parse_xhs_account
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.profile import XhsProfileTool

PLATFORM = "xiaohongshu"


class XhsAccountDashboardTool(XhsJsApiTool):
    """小红书已登录账号主页监控（薄浏览器 + API 直调）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = XhsProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def fetch_dashboard(self, *, show_browser: bool = False, works_limit: int = 10) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)

        from app.services.playwright_pool import PlaywrightPool

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
            result = await self._fetch_on_page(page, works_limit=works_limit)

        output = (
            self.settings.report_output_dir
            / f"dashboard_{PLATFORM}_{self.tenant_id}_{self.account_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result, output

    async def _fetch_on_page(self, page, *, works_limit: int) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        template_url = await self.pick_api_template_url(page, captured_urls)

        raw_self = await self._profile.fetch_self_info(page, template_url)
        data = raw_self.get("data") or raw_self
        basic = data.get("basic_info") or data.get("user") or data
        user_id = basic.get("user_id") or basic.get("id") or ""

        raw_notes: dict = {}
        if user_id:
            raw_notes = await self._profile.fetch_self_notes(page, template_url, user_id, limit=works_limit)

        raw_mentions = await self._profile.fetch_mentions(page, template_url)

        parsed = parse_xhs_account(raw_self, raw_notes, raw_mentions)
        ok = bool(parsed["account"].get("nickname") or parsed["account"].get("user_id"))

        diagnostic_parts: list[str] = []
        if not ok:
            diagnostic_parts.append("未能获取个人主页数据，请确认登录态有效或设置 show_browser=true。")
        if not parsed["works"]:
            diagnostic_parts.append("笔记列表为空或接口未返回。")

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "capture_method": "thin_nav_api",
            "works_limit": works_limit,
            "ok": ok,
            "diagnostic": "；".join(diagnostic_parts) if diagnostic_parts else None,
            **parsed,
        }
