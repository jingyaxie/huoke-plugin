from __future__ import annotations

import asyncio
import json
import re
import contextlib
import random
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from app.core.antibot import headless_for_platform, human_click, human_delay, human_scroll, human_type, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.js_constants import (
    PLATFORM,
    SEARCH_NOTES_PATH,
    _is_search_result_api,
)
from app.platforms.search_filters import (
    SearchFilterOptions,
    fetch_multiplier,
    filter_diagnostic_suffix,
    filter_search_items,
    select_rows_after_filter,
)
from app.platforms.xiaohongshu.utils import build_note_url, find_xsec_in_payload, parse_note_card, walk_note_ids
from app.services.playwright_pool import PlaywrightPool

# 探索页顶区搜索在信息流上方（#search-input-in-feeds），header 内 #search-input 常为 0×0 占位
_TOP_SEARCH_SELECTORS = (
    "#search-input-in-feeds",
    ".input-box.search-box-in-content",
    ".search-area-in-header",
    ".search-area-in-header .search-input",
    ".search-area .search-input",
    "#search-input",
    ".search-input",
)

_SEARCH_SUBMIT_SELECTORS = (
    "#search-input-in-feeds .submit-button-wrapper:not(.disabled)",
    "#search-input-in-feeds .bottom-box-right-submit-button",
    ".search-box-in-content .submit-button-wrapper:not(.disabled)",
    ".search-area-in-header .submit-button-wrapper:not(.disabled)",
)

_TOP_SEARCH_INNER_SELECTORS = (
    "#search-input-in-feeds textarea",
    "#search-input-in-feeds .textarea",
    "textarea[placeholder*='搜索']",
    "#search-input-in-feeds input",
    "#search-input-in-feeds [contenteditable='true']",
    ".search-box-in-content textarea",
    ".search-box-in-content input",
    ".search-box-in-content [contenteditable='true']",
    "#search-input input",
    ".search-input input",
    '#search-input [contenteditable="true"]',
    'input[placeholder*="搜索"]',
    "header input[type='text']",
)


class XhsSearchTool(XhsJsApiTool):
    """小红书关键词搜索工具（薄浏览器 + API 拦截）。"""

    def entry_url(self) -> str:
        return self.settings.xhs_explore_url or self.settings.xhs_home_url

    @staticmethod
    def _on_search_results_page(url: str | None) -> bool:
        return "search_result" in (url or "")

    async def _top_search_has_layout(self, locator) -> bool:
        try:
            if not await locator.count():
                return False
            aria = await locator.get_attribute("aria-hidden")
            if aria == "true":
                return False
            box = await locator.bounding_box()
            return bool(box and box.get("width", 0) > 40 and box.get("height", 0) > 8)
        except Exception:
            return False

    async def _resolve_top_search_target(self, page):
        """顶栏搜索目标：优先内部 input/contenteditable，否则用 #search-input 容器本身。"""
        for selector in _TOP_SEARCH_INNER_SELECTORS:
            loc = page.locator(selector).first
            if await self._top_search_has_layout(loc):
                return loc
        for selector in _TOP_SEARCH_SELECTORS:
            loc = page.locator(selector).first
            if await self._top_search_has_layout(loc):
                return loc
        return None

    async def top_search_ready(self, page, *, wait_ms: int = 10000) -> bool:
        import time

        deadline = time.monotonic() + wait_ms / 1000.0
        while time.monotonic() < deadline:
            if await self._resolve_top_search_target(page) is not None:
                return True
            with contextlib.suppress(Exception):
                await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)
        return False

    async def _ensure_feeds_top_search(self, page) -> bool:
        with contextlib.suppress(Exception):
            await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(800)
        return await self.top_search_ready(page)

    async def _focus_top_search(self, page, target) -> None:
        with contextlib.suppress(Exception):
            await target.scroll_into_view_if_needed(timeout=5000)
        box = await target.bounding_box()
        if box:
            x = box["x"] + box["width"] * 0.5
            y = box["y"] + box["height"] * 0.5
            await page.mouse.click(x, y)
        else:
            await target.click(force=True, timeout=3000)
        await page.wait_for_timeout(300)
        with contextlib.suppress(Exception):
            await target.evaluate(
                """(el) => {
                  el.focus?.();
                  const inner = el.querySelector('input, [contenteditable="true"]');
                  if (inner) inner.focus();
                }"""
            )

    async def _read_search_text(self, target) -> str:
        try:
            tag = await target.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            tag = ""
        if tag in ("input", "textarea"):
            with contextlib.suppress(Exception):
                return (await target.input_value() or "").strip()
        with contextlib.suppress(Exception):
            inner = target.locator("textarea, input").first
            if await inner.count():
                return (await inner.input_value() or "").strip()
        with contextlib.suppress(Exception):
            return (await target.inner_text() or "").strip()
        return ""

    async def _type_into_top_search(self, page, target, keyword: str) -> None:
        text = keyword.strip()
        await self._focus_top_search(page, target)
        current = await self._read_search_text(target)
        if current == text:
            return
        try:
            tag = await target.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            tag = ""
        editable = target
        if tag not in ("input", "textarea"):
            inner = target.locator("textarea, input").first
            if await inner.count():
                editable = inner
                with contextlib.suppress(Exception):
                    await inner.scroll_into_view_if_needed(timeout=3000)
                await inner.click(timeout=3000)
        try:
            tag = await editable.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            tag = ""
        if tag in ("input", "textarea"):
            await editable.fill("")
            await human_type(page, editable, text, self.settings, tenant_id=self.tenant_id)
            return
        with contextlib.suppress(Exception):
            await target.fill(text)
        if (await self._read_search_text(target)) == text:
            return
        with contextlib.suppress(Exception):
            await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
        await page.keyboard.type(text, delay=random.randint(70, 130))

    async def _trigger_searchbar(self, page, keyword: str) -> bool:
        """探索页顶区搜索框输入关键词并提交，禁止拼接搜索 URL。"""
        if not await self._ensure_feeds_top_search(page):
            return False
        target = await self._resolve_top_search_target(page)
        if target is None:
            return False
        await self._type_into_top_search(page, target, keyword)
        await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")

        async def _submit() -> None:
            for selector in _SEARCH_SUBMIT_SELECTORS:
                btn = page.locator(selector).first
                try:
                    if await btn.count() and await btn.is_visible():
                        await btn.click(timeout=3000)
                        return
                except Exception:
                    continue
            box = await target.bounding_box()
            if box:
                x = box["x"] + box["width"] * 0.92
                y = box["y"] + box["height"] * 0.75
                await page.mouse.click(x, y)
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

    async def _legacy_find_search_input(self, page):
        return await self._resolve_top_search_target(page)

    async def _activate_search_bar(self, page) -> bool:
        return await self.top_search_ready(page)

    async def _find_search_input(self, page):
        return await self._resolve_top_search_target(page)

    async def _maybe_apply_search_publish_filter(
        self,
        page,
        *,
        keyword: str,
        region: str | None,
        days: int | None,
        note_meta: dict[str, dict],
        processed: set[int],
    ) -> str | None:
        """编排任务 UI 搜索：点「筛选 → 发布时间」，与 ui_flow search 对齐。"""
        from app.services.ui_flow.params import UiFlowParams
        from app.services.ui_flow.platforms.xiaohongshu.filter_ui import (
            apply_ui_publish_time_filter,
            needs_ui_publish_filter,
        )
        from app.services.ui_flow.platforms.xiaohongshu.ui_session import XhsUiSession

        ui_params = UiFlowParams(platform=PLATFORM, keyword=keyword, days=days or 0, region=region)
        ctx = XhsUiSession(
            settings=self.settings,
            tenant_id=self.tenant_id,
            account_id=self.account_id,
            params=ui_params,
            page=page,
        )
        if not needs_ui_publish_filter(ctx):
            return None
        filter_label = await apply_ui_publish_time_filter(ctx)
        note_meta.clear()
        processed.clear()
        if not filter_label:
            return None
        suffix = f"发布时间={filter_label}"
        if ctx.state.get("search_filter_verified") is False:
            steps = ctx.state.get("search_filter_steps") or []
            suffix += f"；筛选步骤={'>'.join(str(s) for s in steps)}"
        return suffix

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
        if not self._on_search_results_page(page.url):
            await page.goto(self.entry_url(), wait_until="domcontentloaded", timeout=60000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
        if not await self._ensure_feeds_top_search(page):
            return [], "探索页顶区搜索框未就绪"

        note_meta: dict[str, dict] = {}
        target_count = max(limit * fetch_multiplier(filters), 10)
        processed: set[int] = set()
        pending: list[asyncio.Task] = []

        def on_response(resp) -> None:
            if not _is_search_result_api(resp.url):
                return
            pending.append(
                asyncio.create_task(
                    self._ingest_search_response(resp, note_meta, captured_api_urls, target_count, processed)
                )
            )

        page.on("response", on_response)
        try:
            if not await self._trigger_searchbar(page, search_keyword):
                return [], "未能通过搜索框完成搜索（禁止直接跳转搜索 URL）"
            filter_suffix = await self._maybe_apply_search_publish_filter(
                page,
                keyword=keyword,
                region=region,
                days=days,
                note_meta=note_meta,
                processed=processed,
            )
            note_urls, diagnostic = await self._collect_search_results_on_page(
                page,
                limit=limit,
                filters=filters,
                captured_api_urls=captured_api_urls,
                pending=pending,
                note_meta=note_meta,
                processed=processed,
                region=region,
                days=days,
                search_keyword=search_keyword,
            )
            if filter_suffix and diagnostic:
                diagnostic = f"{diagnostic}；{filter_suffix}"
            elif filter_suffix:
                diagnostic = filter_suffix
            return note_urls, diagnostic
        finally:
            await self._drain_tasks(pending)
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    async def _collect_search_results_on_page(
        self,
        page,
        *,
        limit: int,
        filters: SearchFilterOptions,
        captured_api_urls: list[str],
        pending: list[asyncio.Task],
        note_meta: dict[str, dict],
        processed: set[int],
        region: str | None,
        days: int | None,
        search_keyword: str,
    ) -> tuple[list[str], str | None]:
        await self._drain_tasks(pending)
        from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
            dismiss_ai_search_side_panel,
            scroll_search_results_page,
        )

        for _ in range(10):
            if len(note_meta) >= limit:
                break
            await scroll_search_results_page(page, self.settings, tenant_id=self.tenant_id)
            await self._drain_tasks(pending)
            await page.wait_for_timeout(500)
        await dismiss_ai_search_side_panel(page, self.settings, tenant_id=self.tenant_id)
        # 无论 API 是否已有 note_id，都从 DOM 补全 xsec_token（缺 token 直开易 404）
        await self._collect_note_links_from_dom(page, note_meta, max(limit * 5, 20))

        urls, stats = self._meta_to_urls(note_meta, limit, region=region, days=days)
        if urls:
            diagnostic = f"关键词「{search_keyword}」搜索成功（searchbar_ui，{len(urls)} 条笔记）"
            filter_note = filter_diagnostic_suffix(stats, requested=limit)
            if filter_note:
                diagnostic = f"{diagnostic}；{filter_note}"
            missing_token = int(stats.get("missing_xsec_token") or 0)
            if missing_token:
                diagnostic = (
                    f"{diagnostic}；{missing_token} 条链接仍缺 xsec_token（打开可能 404，"
                    "请确认搜索列表已加载或换关键词）"
                )
            return urls, diagnostic
        return [], "搜索框提交后未返回笔记，请确认 Cookie 有效或搜索框是否可见。"

    async def search_notes_from_existing_page(
        self,
        page,
        keyword: str,
        limit: int,
        region: str | None = None,
        days: int | None = None,
    ) -> tuple[list[str], str | None]:
        """在已有浏览器页内通过搜索框搜索（禁止拼接 search_result URL）。"""
        captured_api_urls: list[str] = []
        return await self._ui_searchbar_keyword_search(
            page,
            keyword=keyword,
            limit=limit,
            captured_api_urls=captured_api_urls,
            region=region,
            days=days,
        )

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
        """兼容旧名：与 _ui_searchbar_keyword_search 相同，禁止 goto 搜索 URL。"""
        return await self._ui_searchbar_keyword_search(
            page,
            keyword=keyword,
            limit=limit,
            captured_api_urls=captured_api_urls,
            region=region,
            days=days,
        )

    @staticmethod
    async def _drain_tasks(tasks: list[asyncio.Task]) -> None:
        if not tasks:
            return
        batch = list(tasks)
        tasks.clear()
        await asyncio.gather(*batch, return_exceptions=True)

    async def _ingest_search_response(
        self,
        resp,
        note_meta: dict[str, dict],
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
        self._ingest_search_payload(data, note_meta, target_count)

    def _ingest_search_payload(self, data: dict, note_meta: dict[str, dict], target_count: int) -> None:
        items = (data.get("data") or {}).get("items") or data.get("items") or []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            parsed = parse_note_card(raw, rank=0, tenant_id=self.tenant_id)
            if parsed:
                note_id = parsed["external_id"]
                note_meta[note_id] = {
                    "note_id": note_id,
                    "title": parsed.get("title") or "",
                    "ip_location": parsed.get("ip_location") or "",
                    "create_time": parsed.get("create_time"),
                    "video_url": parsed.get("video_url"),
                    "xsec_token": parsed.get("raw_data", {}).get("xsec_token"),
                    "xsec_source": parsed.get("raw_data", {}).get("xsec_source"),
                    "raw_data": parsed.get("raw_data"),
                }
            else:
                note_id = str(raw.get("note_id") or raw.get("id") or "")
                if not re.fullmatch(r"[0-9a-fA-F]{16,32}", note_id):
                    continue
                token, source = find_xsec_in_payload(raw)
                note_meta[note_id] = {
                    "note_id": note_id,
                    "title": "",
                    "ip_location": "",
                    "create_time": None,
                    "xsec_token": raw.get("xsec_token") or token,
                    "xsec_source": raw.get("xsec_source") or source or "pc_search",
                    "raw_data": raw,
                }
            if len(note_meta) >= target_count:
                return
        for note_id in walk_note_ids(data):
            if note_id not in note_meta:
                note_meta[note_id] = {"note_id": note_id}
            if len(note_meta) >= target_count:
                return

    async def _collect_note_links_from_dom(self, page, note_meta: dict[str, dict], limit: int) -> None:
        from app.platforms.xiaohongshu.utils import extract_note_access_params

        links = await page.locator('a[href*="/explore/"], a[href*="/discovery/item/"]').evaluate_all(
            "els => els.map(e => e.href)"
        )
        for href in links:
            match = re.search(r"(?:/explore/|/discovery/item/)([0-9a-fA-F]{16,32})", href or "")
            if not match:
                continue
            note_id = match.group(1)
            meta = note_meta.setdefault(note_id, {"note_id": note_id})
            access = extract_note_access_params(href or "")
            if access.get("xsec_token") and not meta.get("xsec_token"):
                meta["xsec_token"] = access["xsec_token"]
            if access.get("xsec_source") and not meta.get("xsec_source"):
                meta["xsec_source"] = access["xsec_source"]
            if len(note_meta) >= limit:
                break

    def _meta_to_urls(
        self,
        note_meta: dict[str, dict],
        limit: int,
        *,
        region: str | None = None,
        days: int | None = None,
    ) -> tuple[list[str], dict]:
        from app.platforms.xiaohongshu.utils import extract_note_access_params, resolve_note_open_url

        items = list(note_meta.values())
        filtered, stats = filter_search_items(
            items,
            region=region,
            days=days,
            platform=PLATFORM,
            limit=limit,
        )
        rows = select_rows_after_filter(items, filtered, region=region, limit=limit)
        rows = sorted(
            rows,
            key=lambda meta: (0 if meta.get("xsec_token") or extract_note_access_params(
                str(meta.get("video_url") or meta.get("note_url") or "")
            ).get("xsec_token") else 1),
        )
        urls: list[str] = []
        missing_xsec_token = 0
        for meta in rows:
            note_id = meta.get("note_id") or ""
            if not note_id:
                continue
            open_url = resolve_note_open_url(
                note_id,
                content_url=meta.get("video_url") or meta.get("note_url"),
                note_meta=meta,
                raw_data=meta.get("raw_data") if isinstance(meta.get("raw_data"), dict) else None,
            )
            if not extract_note_access_params(open_url).get("xsec_token"):
                missing_xsec_token += 1
            urls.append(open_url)
            if len(urls) >= limit:
                break
        if missing_xsec_token:
            stats = {**stats, "missing_xsec_token": missing_xsec_token}
        return urls[:limit], stats

    async def search_notes_by_keyword(
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
                return await self.search_notes_from_existing_page(page, keyword, limit, region=region, days=days)
            return await self._ui_searchbar_keyword_search(
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
            / f"search_notes_{PLATFORM}_{self.tenant_id}_{safe_keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def search_notes(
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
            note_urls, diagnostic = await self._ui_searchbar_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
            )

        notes: list[dict] = []
        seen: set[str] = set()
        for url in note_urls:
            match = re.search(r"(?:/explore/|/discovery/item/)([0-9a-fA-F]{16,32})", url)
            if not match:
                continue
            note_id = match.group(1)
            if note_id in seen:
                continue
            seen.add(note_id)
            notes.append({"note_id": note_id, "note_url": url.split("?")[0] if "?" not in url else url})

        payload = {
            "platform": PLATFORM,
            "keyword": keyword,
            "search_keyword": filters.composed_keyword(),
            "region": region,
            "days": days,
            "note_count": len(notes),
            "capture_method": "thin_nav_api" if notes else "empty",
            "diagnostic": diagnostic,
            "notes": notes[:limit],
        }
        output = self._search_output_path(keyword)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
