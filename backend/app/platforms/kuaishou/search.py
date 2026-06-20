from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, human_click, human_delay, human_scroll, human_type, require_login
from app.core.config import Settings
from app.platforms.kuaishou.constants import PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.js_constants import (
    _FIRE_FETCH_JS,
    _build_search_feed_body,
    _is_search_result_api,
)
from app.platforms.kuaishou.utils import build_search_url, build_video_url, parse_search_feed_item
from app.platforms.search_filters import (
    SearchFilterOptions,
    fetch_multiplier,
    filter_diagnostic_suffix,
    filter_search_items,
    select_rows_after_filter,
)
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

_SEARCH_INPUT_SELECTORS = (
    'input[placeholder*="搜索"]',
    ".search-input input",
    'input[type="search"]',
    "header input[type='text']",
)


class KuaishouSearchTool(KuaishouJsApiTool):
    """快手关键词搜索工具（薄浏览器 + API 拦截）。"""

    def entry_url(self) -> str:
        return self.settings.kuaishou_home_url

    @staticmethod
    def _on_search_results_page(url: str | None) -> bool:
        return "/search/" in (url or "")

    async def _find_search_input(self, page):
        for selector in _SEARCH_INPUT_SELECTORS:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                return loc
        return None

    async def _trigger_searchbar(self, page, keyword: str) -> bool:
        """通过顶栏搜索框输入关键词并提交，禁止拼接搜索 URL。"""
        search_input = await self._find_search_input(page)
        if search_input is None:
            return False
        await human_click(page, search_input, self.settings, tenant_id=self.tenant_id)
        try:
            current = (await search_input.input_value() or "").strip()
        except Exception:
            current = ""
        if current != keyword.strip():
            await search_input.fill("")
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
            await human_type(page, search_input, keyword, self.settings, tenant_id=self.tenant_id)

        async def _submit() -> None:
            for selector in ('button:has-text("搜索")', ".search-icon", '[class*="search-btn"]'):
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    await human_click(page, btn, self.settings, tenant_id=self.tenant_id)
                    return
            await page.keyboard.press("Enter")

        try:
            async with page.expect_response(
                lambda resp: _is_search_result_api(resp.url) and resp.status == 200,
                timeout=35000,
            ):
                await _submit()
        except Exception:
            await _submit()
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")

        for _ in range(14):
            if self._on_search_results_page(page.url):
                return True
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
        return self._on_search_results_page(page.url)

    async def _ui_searchbar_keyword_search(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        captured_api_urls: list[str],
        region: str | None = None,
        days: int | None = None,
    ) -> tuple[list[str], str | None]:
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        search_keyword = filters.composed_keyword()
        await page.goto(self.entry_url(), wait_until="domcontentloaded", timeout=120000)
        await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")

        api_items: dict[str, dict] = {}
        target_count = max(limit * fetch_multiplier(filters), 10)
        processed: set[int] = set()
        pending: list[asyncio.Task] = []

        def on_response(resp) -> None:
            if not _is_search_result_api(resp.url):
                return
            pending.append(
                asyncio.create_task(
                    self._ingest_search_response(resp, api_items, captured_api_urls, target_count, processed)
                )
            )

        page.on("response", on_response)
        try:
            if not await self._trigger_searchbar(page, search_keyword):
                return [], "未能通过搜索框完成搜索（禁止直接跳转搜索 URL）"
            await self._drain_tasks(pending)
            for _ in range(8):
                if len(api_items) >= limit:
                    break
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
                await self._drain_tasks(pending)
                await page.wait_for_timeout(500)
            if not api_items:
                await self._collect_video_links_from_dom(page, api_items, limit)
        finally:
            await self._drain_tasks(pending)
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        urls, stats = self._items_to_urls(api_items, limit, region=region, days=days)
        if urls:
            diagnostic = f"关键词「{search_keyword}」搜索成功（searchbar_ui，{len(urls)} 条视频）"
            filter_note = filter_diagnostic_suffix(stats, requested=limit)
            if filter_note:
                diagnostic = f"{diagnostic}；{filter_note}"
            return urls, diagnostic
        return [], "搜索框提交后未返回视频，请确认 Cookie 有效或搜索框是否可见。"

    async def search_videos_from_existing_page(
        self,
        page,
        keyword: str,
        limit: int,
        region: str | None = None,
        days: int | None = None,
    ) -> tuple[list[str], str | None]:
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        search_keyword = filters.composed_keyword()
        api_items: dict[str, dict] = {}

        async def on_response(resp):
            try:
                if not _is_search_result_api(resp.url) or resp.status != 200:
                    return
                data = await resp.json()
            except Exception:
                return
            self._ingest_search_payload(data, api_items, limit * 3)

        page.on("response", on_response)
        try:
            await page.goto(build_search_url(search_keyword), wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            for _ in range(8):
                if len(api_items) >= limit:
                    break
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
            if not api_items:
                await self._collect_video_links_from_dom(page, api_items, limit)
            urls, _ = self._items_to_urls(api_items, limit, region=region, days=days)
            diagnostic = "已在可见浏览器中完成快手关键词搜索。" if urls else "可见浏览器未提取到视频链接。"
            return urls, diagnostic
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    async def _thin_browser_keyword_search(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        captured_api_urls: list[str],
        region: str | None = None,
        days: int | None = None,
    ) -> tuple[list[str], str | None]:
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        search_keyword = filters.composed_keyword()
        await self.warmup_for_js_api(page, captured_api_urls)
        api_items: dict[str, dict] = {}
        target_count = max(limit * fetch_multiplier(filters), 10)
        processed: set[int] = set()
        pending: list[asyncio.Task] = []

        def on_response(resp) -> None:
            if not _is_search_result_api(resp.url):
                return
            pending.append(
                asyncio.create_task(
                    self._ingest_search_response(resp, api_items, captured_api_urls, target_count, processed)
                )
            )

        page.on("response", on_response)
        try:
            await page.goto(build_search_url(search_keyword), wait_until="domcontentloaded", timeout=120000)
            await self._drain_tasks(pending)
            if len(api_items) < limit:
                template_url = await self.pick_api_template_url(page, captured_api_urls)
                await self._fire_search_feed_request(
                    page,
                    search_keyword,
                    template_url,
                    api_items,
                    captured_api_urls,
                    pending,
                    processed,
                    target_count,
                )
                await self._drain_tasks(pending)
            for _ in range(6):
                if len(api_items) >= limit:
                    break
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
                await self._drain_tasks(pending)
                await page.wait_for_timeout(500)
            if not api_items:
                await self._collect_video_links_from_dom(page, api_items, limit)
        finally:
            await self._drain_tasks(pending)
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        urls, stats = self._items_to_urls(api_items, limit, region=region, days=days)
        if urls:
            diagnostic = f"关键词「{search_keyword}」搜索成功（thin_nav_api，{len(urls)} 条视频）"
            filter_note = filter_diagnostic_suffix(stats, requested=limit)
            if filter_note:
                diagnostic = f"{diagnostic}；{filter_note}"
            return urls, diagnostic
        return [], "薄浏览器搜索未返回视频，请确认 Cookie 有效或在本机有头浏览器 手动搜索后设 show_browser=true。"

    @staticmethod
    async def _drain_tasks(tasks: list[asyncio.Task]) -> None:
        if not tasks:
            return
        batch = list(tasks)
        tasks.clear()
        await asyncio.gather(*batch, return_exceptions=True)

    async def _fire_search_feed_request(
        self,
        page,
        keyword: str,
        template_url: str,
        api_items: dict[str, dict],
        captured_api_urls: list[str],
        pending: list[asyncio.Task],
        processed: set[int],
        target_count: int,
    ) -> None:
        body = _build_search_feed_body(keyword)
        try:
            async with page.expect_response(lambda resp: _is_search_result_api(resp.url), timeout=15000) as resp_info:
                await page.evaluate(_FIRE_FETCH_JS, {"url": template_url, "body": body, "timeoutMs": 15000})
            await self._ingest_search_response(
                await resp_info.value, api_items, captured_api_urls, target_count, processed
            )
        except Exception:
            await page.evaluate(_FIRE_FETCH_JS, {"url": template_url, "body": body, "timeoutMs": 15000})

    async def _ingest_search_response(
        self,
        resp,
        api_items: dict[str, dict],
        captured_api_urls: list[str],
        target_count: int,
        processed: set[int],
    ) -> None:
        if id(resp) in processed:
            return
        url = resp.url
        if url not in captured_api_urls:
            captured_api_urls.append(url)
        try:
            data = await resp.json()
        except Exception:
            try:
                raw = await resp.body()
                data = json.loads(raw.decode("utf-8", errors="ignore") or "{}")
            except Exception:
                return
        if not isinstance(data, dict):
            return
        processed.add(id(resp))
        self._ingest_search_payload(data, api_items, target_count)

    def _ingest_search_payload(self, data: dict, api_items: dict[str, dict], target_count: int) -> None:
        if int(data.get("result") or 0) not in (0, 1):
            return
        for feed in data.get("feeds") or []:
            row = parse_search_feed_item(feed, tenant_id=self.tenant_id)
            if not row:
                continue
            api_items.setdefault(row["photo_id"], row)
            if len(api_items) >= target_count:
                return

    async def _collect_video_links_from_dom(self, page, api_items: dict[str, dict], limit: int) -> None:
        links = await page.locator('a[href*="/short-video/"]').evaluate_all("els => els.map(e => e.href)")
        for href in links:
            match = re.search(r"/short-video/([0-9a-zA-Z]+)", href or "")
            if match:
                photo_id = match.group(1)
                api_items.setdefault(
                    photo_id,
                    {
                        "photo_id": photo_id,
                        "video_url": build_video_url(photo_id),
                        "title": "",
                        "author": "",
                        "author_id": "",
                    },
                )
            if len(api_items) >= limit:
                break

    def _items_to_urls(
        self,
        api_items: dict[str, dict],
        limit: int,
        *,
        region: str | None = None,
        days: int | None = None,
    ) -> tuple[list[str], dict]:
        items = list(api_items.values())
        filtered, stats = filter_search_items(
            items,
            region=region,
            days=days,
            platform=PLATFORM,
            limit=limit,
        )
        rows = select_rows_after_filter(items, filtered, region=region, limit=limit)
        urls: list[str] = []
        for row in rows:
            url = row.get("video_url") or build_video_url(row.get("photo_id") or "")
            if url:
                urls.append(url.split("?")[0])
            if len(urls) >= limit:
                break
        return urls[:limit], stats

    async def search_videos_by_keyword(
        self,
        keyword: str,
        limit: int,
        headless: bool | None = None,
        manual_search: bool = False,
        region: str | None = None,
        days: int | None = None,
        *,
        ui_search_only: bool = False,
    ) -> tuple[list[str], str | None]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        resolved_headless = headless_for_platform(self.settings, PLATFORM, headless)
        captured_api_urls: list[str] = []
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, page):
            if manual_search:
                return await self.search_videos_from_existing_page(page, keyword, limit, region=region, days=days)
            if ui_search_only:
                return await self._ui_searchbar_keyword_search(
                    page,
                    keyword=keyword,
                    limit=limit,
                    captured_api_urls=captured_api_urls,
                    region=region,
                    days=days,
                )
            return await self._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
            )

    def _search_output_path(self, keyword: str) -> Path:
        safe_keyword = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", keyword)[:32]
        path = (
            self.settings.report_output_dir
            / f"search_videos_{PLATFORM}_{self.tenant_id}_{safe_keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def search_videos(
        self,
        keyword: str,
        limit: int = 10,
        show_browser: bool = False,
        region: str | None = None,
        days: int | None = None,
    ) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        headless = headless_for_platform(self.settings, PLATFORM, not show_browser)
        captured_api_urls: list[str] = []
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=headless,
            account_id=self.account_id,
        ) as (_, page):
            video_urls, diagnostic = await self._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
            )

        videos: list[dict] = []
        seen: set[str] = set()
        for url in video_urls:
            match = re.search(r"/short-video/([0-9a-zA-Z]+)", url)
            if not match:
                continue
            photo_id = match.group(1)
            if photo_id in seen:
                continue
            seen.add(photo_id)
            videos.append({"photo_id": photo_id, "video_url": url.split("?")[0]})

        payload = {
            "platform": PLATFORM,
            "keyword": keyword,
            "search_keyword": filters.composed_keyword(),
            "region": region,
            "days": days,
            "video_count": len(videos),
            "capture_method": "thin_nav_api" if videos else "empty",
            "diagnostic": diagnostic,
            "videos": videos[:limit],
        }
        output = self._search_output_path(keyword)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
