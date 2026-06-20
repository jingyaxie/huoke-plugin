from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from app.core.antibot import (
    headless_for_platform,
    human_delay,
    require_login,
)
from app.core.config import Settings
from app.platforms.douyin.js_constants import (
    PLATFORM,
    _SEARCH_API_EXCLUDES,
    _SEARCH_RESULT_API_MARKERS,
)
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.search_filters import (
    SearchFilterOptions,
    filter_diagnostic_suffix,
    filter_search_items,
    select_rows_after_filter,
)
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool
from app.platforms.douyin.human_guards import HumanBrowseGuardError

_JS_REMOVED_HINT = (
    "抖音已移除 JS API 搜索，请使用任务模式（ui_search_only）或 show_browser=true 走搜索框 UI"
)


class DouyinSearchTool:
    """抖音关键词搜索：精选页搜索框 UI + 被动拦截 search API。"""

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
        self.platform = PLATFORM
        self.store = store or DouyinSessionStore(settings)

    def entry_url(self) -> str:
        """UI 搜索回退入口（热榜页，已验证可点搜索框）。"""
        return self.settings.douyin_hot_url

    @staticmethod
    def _search_nil_diagnostic(data: dict) -> str | None:
        nil = data.get("search_nil_info")
        if not isinstance(nil, dict):
            return None
        nil_type = str(nil.get("search_nil_type") or nil.get("search_nil_item") or "").strip()
        if nil_type == "verify_check":
            return (
                "抖音搜索触发人机验证(verify_check)，Cookie 文件有效但当前会话未通过风控。"
                "请用 show_browser=true 在本机有头浏览器 完成验证后重试。"
            )
        if nil_type:
            return f"抖音搜索无结果(search_nil={nil_type})，请换关键词或在本机有头浏览器 手动搜索。"
        return None

    @staticmethod
    def _record_search_nil(data: dict, search_hints: dict[str, str] | None) -> None:
        if search_hints is None:
            return
        diagnostic = DouyinSearchTool._search_nil_diagnostic(data)
        if not diagnostic:
            return
        nil = data.get("search_nil_info") if isinstance(data.get("search_nil_info"), dict) else {}
        nil_type = str(nil.get("search_nil_type") or nil.get("search_nil_item") or "").strip()
        if nil_type:
            search_hints["nil_type"] = nil_type
        search_hints["diagnostic"] = diagnostic

    async def keyword_search(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        captured_api_urls: list[str],
        region: str | None = None,
        days: int | None = None,
        headless: bool = True,
        manual_search: bool = False,
        search_url_first: bool = False,
        ui_search_only: bool = False,
        watched_skip: int = 0,
    ) -> tuple[list[str], str | None, str]:
        """关键词搜索：仅搜索框 UI（ui_search_only）或 manual_search；已移除 JS/直链搜索。"""
        if search_url_first:
            return [], "search_url_first 已禁用（禁止直链搜索 URL）", ""

        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        api_items: dict[str, dict] = {}
        search_started: dict[str, bool] = {"value": manual_search}
        has_storage_state = self.store.is_ready(self.store.load(self.tenant_id, self.account_id))

        async def on_response(resp) -> None:
            if not search_started["value"]:
                return
            try:
                url = resp.url
                if not self._is_search_result_api(url):
                    return
                data = await resp.json()
            except Exception:
                return
            for row in self._extract_aweme_items_from_json(data):
                api_items.setdefault(row["aweme_id"], row)
                if len(api_items) >= max(limit * 5, 30):
                    break

        page.on("response", on_response)
        try:
            if manual_search:
                urls, diagnostic = await self._collect_search_results(
                    page,
                    keyword=keyword,
                    limit=limit,
                    headless=headless,
                    manual_search=True,
                    keep_general_tab=False,
                    api_items=api_items,
                    has_storage_state=has_storage_state,
                    region=region,
                    days=days,
                )
                return urls, diagnostic, ""

            if not ui_search_only:
                return [], _JS_REMOVED_HINT, ""

            from app.services.ui_flow.platforms.douyin.search_ui import run_searchbar_keyword_search

            search_started["value"] = True
            search_result = await run_searchbar_keyword_search(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                account_id=self.account_id,
                keyword=filters.composed_keyword(),
                limit=limit,
                days=days,
                region=region,
            )
            if not search_result.ok:
                diag = (
                    search_result.diagnostic
                    or search_result.error
                    or "未能通过精选页搜索框完成搜索"
                )
                return [], diag, ""

            urls = list(search_result.data.get("video_urls") or [])
            if not urls:
                aweme_ids = search_result.data.get("search_aweme_ids") or []
                if aweme_ids:
                    urls = [
                        f"https://www.douyin.com/video/{aid.split('?')[0]}"
                        for aid in aweme_ids[:limit]
                        if aid
                    ]
            diagnostic = str(search_result.diagnostic or "")
            if not urls:
                urls, diagnostic = await self._collect_search_results(
                    page,
                    keyword=keyword,
                    limit=limit,
                    headless=headless,
                    manual_search=False,
                    keep_general_tab=True,
                    api_items=api_items,
                    has_storage_state=has_storage_state,
                    region=region,
                    days=days,
                    watched_skip=watched_skip,
                )
            if urls:
                await self._restore_comment_api_context(page)
                return urls[:limit], diagnostic, ""
            return (
                [],
                diagnostic or "搜索框提交后未返回视频，请检查登录态或关键词",
                "",
            )
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

    async def _restore_comment_api_context(self, page, warmup_url: str | None = None) -> None:
        """离开搜索页，避免后续侧栏抓评时上下文异常。"""
        current = page.url or ""
        if "/search/" not in current:
            return
        target = self.settings.douyin_home_url
        await page.goto(target, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(800)

    @staticmethod
    def _is_search_result_api(url: str) -> bool:
        if any(ex in url for ex in _SEARCH_API_EXCLUDES):
            return False
        return any(marker in url for marker in _SEARCH_RESULT_API_MARKERS)

    @staticmethod
    def _keyword_tokens(keyword: str) -> list[str]:
        tokens = [t.strip() for t in re.split(r"[\s,，、]+", keyword) if len(t.strip()) >= 2]
        return tokens or [keyword.strip()]

    def _title_matches_keyword(self, title: str, keyword: str) -> bool:
        if not title:
            return False
        text = title.lower()
        tokens = self._keyword_tokens(keyword)
        core = [t for t in tokens if len(t) >= 3]
        check = core or tokens
        return any(token.lower() in text for token in check)

    def _rank_search_items(self, items: list[dict], keyword: str) -> list[dict]:
        tokens = [t.lower() for t in self._keyword_tokens(keyword)]

        def score(row: dict) -> int:
            title = (row.get("title") or "").lower()
            if not title:
                return 0
            return sum(2 if token in title else 0 for token in tokens)

        ranked = sorted(items, key=lambda row: (score(row), row.get("digg_count") or 0), reverse=True)
        matched = [row for row in ranked if self._title_matches_keyword(row.get("title") or "", keyword)]
        return matched or ranked

    def _finalize_search_results(
        self,
        api_items: dict[str, dict],
        filters: SearchFilterOptions,
        limit: int,
        *,
        mode: str = "ui_search",
    ) -> tuple[list[str], str | None] | None:
        ranked = self._rank_search_items(list(api_items.values()), filters.keyword)
        filtered, stats = filter_search_items(
            ranked,
            region=filters.region,
            days=filters.days,
            platform=PLATFORM,
            limit=limit,
        )
        rows = select_rows_after_filter(ranked, filtered, region=filters.region, limit=limit)
        uniq: list[str] = []
        seen: set[str] = set()
        for row in rows:
            url = row.get("video_url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            uniq.append(url.split("?")[0])
            if len(uniq) >= limit:
                break
        if not uniq:
            return None
        label = "ui_search"
        search_kw = filters.composed_keyword()
        diagnostic = f"关键词「{search_kw}」搜索成功（{label}，{len(uniq)} 条视频）"
        filter_note = filter_diagnostic_suffix(stats, requested=limit)
        if filter_note:
            diagnostic = f"{diagnostic}；{filter_note}"
        if rows and not self._title_matches_keyword(rows[0].get("title") or "", filters.keyword):
            diagnostic = (
                f"{diagnostic}；标题与「{filters.keyword}」匹配度低"
                f"（首条：{rows[0].get('title', '')[:40]}）"
            )
        return uniq[:limit], diagnostic

    async def _collect_search_results(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        headless: bool,
        manual_search: bool,
        keep_general_tab: bool = False,
        api_items: dict[str, dict],
        has_storage_state: bool,
        region: str | None = None,
        days: int | None = None,
        watched_skip: int = 0,
    ) -> tuple[list[str], str | None]:
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        if await self._is_captcha_page(page):
            if headless:
                return [], "关键词搜索命中抖音验证码中间页。请打开 有头浏览器完成验证后重试。"
            for _ in range(120):
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                if not await self._is_captcha_page(page):
                    break
            else:
                return [], "可见浏览器已等待较长时间，验证码仍未通过。请在本机有头浏览器 中手动完成验证。"

        scroll_profile = "scroll" if (manual_search or keep_general_tab) else "fast"
        # ui_search_only（keep_general_tab）仍需在搜索列表内滚动加载更多视频，否则只拿到首批 1～3 条
        scroll_rounds = 12 if manual_search else (10 if keep_general_tab else 4)
        from app.services.ui_flow.platforms.douyin.search_ui import scroll_search_results_page

        if keep_general_tab and not api_items and "/search/" in (page.url or ""):
            for _ in range(14):
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="fast")
                if api_items:
                    break
                await scroll_search_results_page(
                    page,
                    self.settings,
                    tenant_id=self.tenant_id,
                )
        if keep_general_tab and watched_skip > 0:
            scroll_rounds += min(12, max(0, watched_skip // 2))
        for _ in range(scroll_rounds):
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile=scroll_profile)
            await scroll_search_results_page(
                page,
                self.settings,
                tenant_id=self.tenant_id,
            )
            if api_items and len(api_items) >= limit and not keep_general_tab:
                break

        if api_items:
            finalized = self._finalize_search_results(api_items, filters, limit, mode="ui_search")
            if finalized:
                urls, diagnostic = finalized
                if manual_search:
                    diagnostic = "已在可见浏览器中接收到搜索结果。"
                return urls, diagnostic

        ranked = self._rank_search_items(list(api_items.values()), keyword)
        uniq: list[str] = []
        seen: set[str] = set()
        for row in ranked:
            url = row.get("video_url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            uniq.append(url.split("?")[0])
            if len(uniq) >= limit:
                break

        if not uniq and "/search/" in page.url:
            links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
            for href in links:
                if href and href not in seen:
                    seen.add(href)
                    uniq.append(href.split("?")[0])
                if len(uniq) >= limit:
                    break

        if manual_search and not uniq:
            for _ in range(120):
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="poll")
                ranked = self._rank_search_items(list(api_items.values()), keyword)
                if ranked:
                    uniq = [row["video_url"].split("?")[0] for row in ranked[:limit]]
                    break
                links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
                if links:
                    uniq = [h.split("?")[0] for h in links[:limit]]
                    break

        diagnostic: str | None = None
        if not uniq:
            if not has_storage_state:
                diagnostic = "未检测到登录 Cookie，请先登录抖音。"
            elif await self._is_captcha_page(page):
                diagnostic = "命中验证码中间页，请在本机有头浏览器 中完成验证。"
            elif "/search/" not in page.url and not api_items:
                diagnostic = "搜索未进入结果页，请确认关键词或在本机有头浏览器 手动搜索后重试。"
            else:
                diagnostic = f"搜索「{keyword}」未找到相关视频，请换关键词或在本机有头浏览器 手动切到「视频」标签后重试。"
        elif ranked and not self._title_matches_keyword(ranked[0].get("title") or "", keyword):
            diagnostic = (
                f"已取搜索结果但标题与「{keyword}」匹配度低"
                f"（首条：{ranked[0].get('title', '')[:40]}），请人工核对。"
            )
        elif manual_search:
            diagnostic = "已在可见浏览器中接收到搜索结果。"
        return uniq[:limit], diagnostic

    async def search_videos_by_keyword(
        self,
        keyword: str,
        limit: int,
        headless: bool | None = None,
        manual_search: bool = False,
        region: str | None = None,
        days: int | None = None,
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
            urls, diagnostic, _ = await self.keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
                headless=resolved_headless,
                manual_search=manual_search,
                ui_search_only=True,
            )
            return urls, diagnostic

    async def _is_captcha_page(self, page) -> bool:
        try:
            title = (await page.title()) or ""
            if "验证码中间页" in title:
                return True
            body_text = await page.locator("body").inner_text(timeout=1500)
            return "验证码中间页" in body_text
        except Exception:
            return False

    def _extract_aweme_ids_from_json(self, data) -> list[str]:
        ids: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "aweme_id" and isinstance(v, (str, int)):
                        vid = str(v)
                        if re.fullmatch(r"\d{8,22}", vid):
                            ids.append(vid)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        uniq: list[str] = []
        seen = set()
        for vid in ids:
            if vid in seen:
                continue
            seen.add(vid)
            uniq.append(vid)
        return uniq

    def _normalize_search_aweme(self, node: dict) -> dict | None:
        aweme = node.get("aweme_info") if isinstance(node.get("aweme_info"), dict) else node
        if not isinstance(aweme, dict):
            return None
        aweme_id = str(aweme.get("aweme_id") or "")
        if not re.fullmatch(r"\d{8,22}", aweme_id):
            return None
        author = aweme.get("author") or {}
        stats = aweme.get("statistics") or {}
        poi = aweme.get("poi_info") or {}
        return {
            "aweme_id": aweme_id,
            "video_url": f"https://www.douyin.com/video/{aweme_id}",
            "title": (aweme.get("desc") or "").strip(),
            "author": (author.get("nickname") or "").strip(),
            "author_id": str(author.get("uid") or ""),
            "sec_uid": author.get("sec_uid") or "",
            "digg_count": int(stats.get("digg_count") or 0),
            "comment_count": int(stats.get("comment_count") or 0),
            "share_count": int(stats.get("share_count") or 0),
            "create_time": aweme.get("create_time"),
            "ip_label": (aweme.get("ip_label") or "").strip(),
            "poi_name": (poi.get("poi_name") or "").strip(),
            "poi_address": (poi.get("address") or poi.get("poi_address") or "").strip(),
        }

    def _extract_aweme_items_from_json(self, data) -> list[dict]:
        items: list[dict] = []
        seen: set[str] = set()

        def walk(node) -> None:
            if isinstance(node, dict):
                if "aweme_info" in node or (
                    "aweme_id" in node and ("desc" in node or "author" in node)
                ):
                    row = self._normalize_search_aweme(node)
                    if row and row["aweme_id"] not in seen:
                        seen.add(row["aweme_id"])
                        items.append(row)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return items

    def _search_videos_output_path(self, keyword: str) -> Path:
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
        *,
        ui_search_only: bool = False,
        existing_page=None,
    ) -> tuple[dict, Path]:
        """关键词搜索视频，返回结构化结果与报告路径。"""
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        headless = headless_for_platform(self.settings, PLATFORM, not show_browser)
        captured_api_urls: list[str] = []

        async def _run_keyword_search(page):
            return await self.keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
                headless=headless,
                manual_search=False,
                ui_search_only=True,
            )

        if existing_page is not None and not existing_page.is_closed():
            video_urls, diagnostic, _ = await _run_keyword_search(existing_page)
        else:
            pool = PlaywrightPool.get()
            async with pool.tenant_context(
                PLATFORM,
                self.tenant_id,
                self.store,
                self.settings,
                headless=headless,
                account_id=self.account_id,
            ) as (_, page):
                video_urls, diagnostic, _ = await _run_keyword_search(page)

        videos: list[dict] = []
        seen: set[str] = set()
        for url in video_urls:
            match = re.search(r"/video/(\d{8,22})", url)
            if not match:
                continue
            aweme_id = match.group(1)
            if aweme_id in seen:
                continue
            seen.add(aweme_id)
            videos.append({"aweme_id": aweme_id, "video_url": url.split("?")[0]})

        capture_method = "ui_flow_douyin_search_ui" if videos else "empty"
        payload = {
            "platform": PLATFORM,
            "keyword": keyword,
            "search_keyword": filters.composed_keyword(),
            "region": region,
            "days": days,
            "video_count": len(videos),
            "capture_method": capture_method,
            "diagnostic": diagnostic,
            "videos": videos[:limit],
        }
        output = self._search_videos_output_path(keyword)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
