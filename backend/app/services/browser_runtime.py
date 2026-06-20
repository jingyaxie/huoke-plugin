from __future__ import annotations

import random
from typing import Any

from playwright.async_api import Page

from app.core.antibot import human_delay, human_scroll
from app.core.config import Settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.agent_network_capture import NetworkCapture


class BrowserRuntime:
    """底层浏览器运行时：Chrome 仿真 + 人类行为 + 通用接口拦截。

    不包含任何平台/页面的业务解析逻辑；业务由 Skill（instruction/actions）驱动。
    """

    def __init__(self, session: AgentBrowserSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    @property
    def capture(self) -> NetworkCapture:
        return self.session.network_capture

    async def ensure_page(self) -> Page:
        return await self.session.ensure_started()

    async def warmup(self, home_url: str | None = None) -> dict[str, Any]:
        if not self.settings.antibot_warmup_enabled:
            return {"skipped": True, "reason": "ANTIBOT_WARMUP_ENABLED=false"}
        page = await self.ensure_page()
        url = home_url or self._default_home_url()
        if not url:
            return {"skipped": True, "reason": "no_home_url"}
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=120000)
        except Exception as exc:
            return {"skipped": True, "reason": str(exc)}
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="warmup")
        await human_scroll(page, self.settings, tenant_id=self.session.tenant_id)
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="warmup")
        info = await self.session.page_info()
        return {"warmed_up": True, "url": info["url"], "title": info["title"]}

    async def browse(
        self,
        url: str,
        *,
        warmup_first: bool = False,
        home_url: str | None = None,
        scroll_rounds: int = 2,
        wait_until: str = "domcontentloaded",
    ) -> dict[str, Any]:
        page = await self.ensure_page()
        if warmup_first:
            await self.warmup(home_url)
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="page_load")
        response = await page.goto(url, wait_until=wait_until, timeout=120000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="page_load")
        for _ in range(max(0, scroll_rounds)):
            await human_scroll(page, self.settings, tenant_id=self.session.tenant_id)
            if random.random() < 0.35:
                await human_delay(page, self.settings, tenant_id=self.session.tenant_id, profile="warmup")
        info = await self.session.page_info()
        return {
            "url": info["url"],
            "title": info["title"],
            "status": response.status if response else None,
            "scroll_rounds": scroll_rounds,
            "api_capture_count": len(self.capture.entries),
        }

    async def wait_api(
        self,
        *,
        url_contains: str | None = None,
        min_count: int = 1,
        timeout_ms: int = 15000,
        poll_ms: int = 400,
    ) -> dict[str, Any]:
        found = await self.capture.wait_until(
            url_contains=url_contains,
            min_count=min_count,
            timeout_ms=timeout_ms,
            poll_ms=poll_ms,
        )
        items = self.capture.query(url_contains=url_contains, limit=20, include_data=False)
        return {
            "matched": found,
            "url_contains": url_contains,
            "count": len(items),
            "paths": [item["path"] for item in items[:10]],
        }

    def query_api(
        self,
        *,
        url_contains: str | None = None,
        limit: int = 5,
        include_data: bool = True,
        clear_buffer: bool = False,
    ) -> dict[str, Any]:
        items = self.capture.query(
            url_contains=url_contains,
            limit=max(1, min(limit, 20)),
            include_data=include_data,
        )
        if clear_buffer:
            self.capture.clear()
        return {
            "url_contains": url_contains,
            "count": len(items),
            "items": items,
            "hint": "原始 JSON 由浏览器自动拦截，业务解析由 Skill/Agent 完成，不在底层写死",
        }

    def _default_home_url(self) -> str | None:
        platform = self.session.platform
        if platform == "douyin":
            return self.settings.douyin_home_url
        if platform == "xiaohongshu":
            return self.settings.xhs_home_url
        if platform == "kuaishou":
            return self.settings.kuaishou_home_url
        return None
