from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.account_dashboard_parsers import parse_douyin_account
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.douyin.profile import DouyinProfileTool
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

PLATFORM = "douyin"


class DouyinAccountDashboardTool(DouyinJsApiTool):
    """抖音已登录账号主页监控（薄浏览器 + API 直调）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        super().__init__(settings, tenant_id, store, account_id=account_id)
        self._profile = DouyinProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def fetch_dashboard(self, *, show_browser: bool = False, works_limit: int = 10) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        state = self.store.load(self.tenant_id, self.account_id) or {}
        logged_in = isinstance(self.store, DouyinSessionStore) and self.store.is_user_logged_in(state)

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
            result = await self._fetch_on_page(page, works_limit=works_limit, logged_in=logged_in)

        output = (
            self.settings.report_output_dir
            / f"dashboard_{PLATFORM}_{self.tenant_id}_{self.account_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result, output

    async def _fetch_on_page(self, page, *, works_limit: int, logged_in: bool) -> dict:
        captured_urls: list[str] = []
        await self.warmup_for_js_api(page, captured_urls)
        template_url = await self.pick_api_template_url(page, captured_urls)

        raw_profile = await self._profile.fetch_self_profile(page, template_url)
        user = raw_profile.get("user") or raw_profile.get("user_info") or {}
        sec_uid = user.get("sec_uid") or ""

        raw_works: dict = {}
        if sec_uid:
            raw_works = await self._profile.fetch_self_works(page, template_url, sec_uid, limit=works_limit)

        raw_notice = await self._profile.fetch_notice_count(page, template_url)

        raw_im: dict = {}
        try:
            if page.is_closed():
                raise RuntimeError("page closed")
            await page.goto("https://www.douyin.com/im", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)
            im_template = await self.pick_api_template_url(page, captured_urls) or template_url
            raw_im = await self._profile.fetch_im_spotlight(page, im_template)
        except Exception:
            if not page.is_closed():
                raw_im = await self._profile.fetch_im_spotlight(page, template_url)

        parsed = parse_douyin_account(raw_profile, raw_works, raw_notice, raw_im)
        ok = bool(parsed["account"].get("nickname") or parsed["account"].get("sec_uid"))

        diagnostic_parts: list[str] = []
        if not logged_in:
            diagnostic_parts.append("当前为游客态 Cookie，部分数据可能不完整，请使用扫码登录账号。")
        if not ok:
            diagnostic_parts.append("未能获取个人主页数据，请确认登录态有效或设置 show_browser=true。")
        if not parsed["works"]:
            diagnostic_parts.append("作品列表为空或接口未返回。")

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "logged_in": logged_in,
            "capture_method": "thin_nav_api",
            "works_limit": works_limit,
            "ok": ok,
            "diagnostic": "；".join(diagnostic_parts) if diagnostic_parts else None,
            **parsed,
        }
