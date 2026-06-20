from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.account_dashboard_parsers import parse_kuaishou_account
from app.platforms.kuaishou.constants import PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.profile import KuaishouProfileTool
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class KuaishouAccountDashboardTool(KuaishouJsApiTool):
    """快手已登录账号主页监控（薄浏览器 + API 直调）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = KuaishouProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def fetch_dashboard(self, *, show_browser: bool = False, works_limit: int = 10) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        user_id = self._extract_user_id()
        if not user_id:
            raise ValueError("快手 Cookie 中缺少 userId，请重新登录")

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
            result = await self._fetch_on_page(page, user_id=user_id, works_limit=works_limit)

        output = (
            self.settings.report_output_dir
            / f"dashboard_{PLATFORM}_{self.tenant_id}_{self.account_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result, output

    def _extract_user_id(self) -> str:
        state = self.store.load(self.tenant_id, self.account_id) or {}
        for cookie in state.get("cookies") or []:
            if isinstance(cookie, dict) and cookie.get("name") == "userId":
                return str(cookie.get("value") or "")
        return ""

    async def _fetch_on_page(self, page, *, user_id: str, works_limit: int) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        template_url = await self.pick_api_template_url(page, captured_urls)

        profile_url = await self._profile.open_profile(page, user_id, wait_ms=2000)
        raw_profile = await self._profile.fetch_user_profile(page, template_url, user_id)
        raw_works = await self._profile.fetch_user_works(page, user_id, limit=works_limit)

        parsed = parse_kuaishou_account(raw_profile, raw_works)
        ok = bool(parsed["account"].get("nickname") or parsed["account"].get("user_id"))

        diagnostic_parts: list[str] = []
        if not ok:
            diagnostic_parts.append("未能获取个人主页数据，请确认登录态有效或设置 show_browser=true。")
        if not parsed["works"]:
            diagnostic_parts.append("作品列表为空或 GraphQL 未返回。")

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "profile_url": profile_url,
            "capture_method": "thin_nav_api",
            "works_limit": works_limit,
            "ok": ok,
            "diagnostic": "；".join(diagnostic_parts) if diagnostic_parts else None,
            **parsed,
        }
