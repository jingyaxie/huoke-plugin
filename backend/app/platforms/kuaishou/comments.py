from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, human_pause, require_login
from app.core.config import Settings
from app.platforms.kuaishou.comment_tool import KuaishouCommentTool
from app.platforms.kuaishou.constants import PLATFORM, REQUIRED_LOGIN_COOKIES
from app.platforms.kuaishou.crawler import KuaishouCrawler
from app.platforms.kuaishou.js_constants import DEFAULT_MAX_COMMENTS
from app.platforms.search_filters import SearchFilterOptions
from app.platforms.kuaishou.search import KuaishouSearchTool
from app.platforms.kuaishou.session import KuaishouSessionStore
from app.platforms.kuaishou.utils import extract_photo_id
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class KuaishouCommentCrawler:
    """组合搜索工具与评论工具的门面。"""

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
        self.store = store or KuaishouSessionStore(settings)
        self._search = KuaishouSearchTool(settings, tenant_id, self.store, account_id=account_id)
        self._comments = KuaishouCommentTool(settings, tenant_id, self.store, account_id=account_id)
        self.hot_crawler = KuaishouCrawler(settings, tenant_id, self.store, account_id=account_id)

    async def crawl_video_comments(self, *args, **kwargs):
        return await self._comments.crawl_video_comments(*args, **kwargs)

    async def crawl_note_comments(self, *args, **kwargs):
        return await self._comments.crawl_note_comments(*args, **kwargs)

    async def search_videos(self, *args, **kwargs):
        return await self._search.search_videos(*args, **kwargs)

    async def search_videos_by_keyword(self, *args, **kwargs):
        return await self._search.search_videos_by_keyword(*args, **kwargs)

    async def search_videos_from_existing_page(self, *args, **kwargs):
        return await self._search.search_videos_from_existing_page(*args, **kwargs)

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int = 3,
        region: str | None = None,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        guest_mode: bool = False,
        existing_page=None,
        manual_search: bool = False,
        search_url_first: bool = False,
        ui_search_only: bool = False,
        ui_first: bool = False,
        ui_flow_context: dict | None = None,
        **_,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        if guest_mode:
            raise ValueError("guest_mode 仅支持抖音平台")
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if ui_search_only and existing_page is None:
            return (
                [],
                [],
                "UI 搜索需要任务浏览器会话（禁止 PlaywrightPool 临时窗口）",
                {"guest_mode": False, "session_mode": "logged_in"},
            )

        if show_browser and not KuaishouCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id):
            await self.hot_crawler.start_interactive_login_session()

        resolved_headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        session_meta = {"guest_mode": False, "session_mode": "logged_in"}

        async def _search_on_page(page) -> tuple[list[str], str | None]:
            if ui_search_only:
                captured_api_urls: list[str] = []
                return await self._search._ui_searchbar_keyword_search(
                    page,
                    keyword=keyword,
                    limit=limit,
                    captured_api_urls=captured_api_urls,
                    region=region,
                    days=days,
                )
            if manual_search:
                return await self._search.search_videos_from_existing_page(
                    page, keyword, limit, region=region, days=days
                )
            captured_api_urls: list[str] = []
            return await self._search._thin_browser_keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
            )

        if existing_page is not None:
            video_urls, diagnostic = await _search_on_page(existing_page)
            results, files = await self._crawl_videos_on_page(
                existing_page,
                video_urls,
                keyword=keyword,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(existing_page)
            return results, files, diagnostic, session_meta

        session = KuaishouCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
        if session:
            page = session["page"]
            video_urls, diagnostic = await _search_on_page(page)
            results, files = await self._crawl_videos_on_page(
                page,
                video_urls,
                keyword=keyword,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, diagnostic, session_meta

        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, page):
            video_urls, diagnostic = await _search_on_page(page)
            results, files = await self._crawl_videos_on_page(
                page,
                video_urls,
                keyword=keyword,
                days=days,
                region=region,
                max_comments=max_comments,
                session_meta=session_meta,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, diagnostic, session_meta

    async def _crawl_videos_on_page(
        self,
        page,
        video_urls: list[str],
        *,
        keyword: str,
        days: int,
        region: str | None,
        max_comments: int,
        session_meta: dict,
    ) -> tuple[list[dict], list[Path]]:
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        results: list[dict] = []
        files: list[Path] = []
        for url in video_urls:
            photo_id = extract_photo_id(url)
            payload = await self._comments._fetch_comments_via_nav(
                page,
                photo_id,
                url,
                max_comments=max_comments,
            )
            payload["platform"] = PLATFORM
            payload["keyword_context"] = {
                "keyword": keyword,
                "search_keyword": filters.composed_keyword(),
                "days": days,
                "region": region,
                "guest_mode": session_meta.get("guest_mode", False),
                "session_mode": session_meta.get("session_mode"),
            }
            payload["video_url"] = payload.get("video_url") or url
            output = (
                self.settings.report_output_dir
                / f"comments_{self.platform}_{self.tenant_id}_{photo_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(payload)
            files.append(output)
            await human_pause(self.settings, tenant_id=self.tenant_id, profile="between_items")
        return results, files

    async def _detect_session_mode_from_page(self, page) -> str:
        try:
            names = {c.get("name") for c in await page.context.cookies() if c.get("name")}
        except Exception:
            return "anonymous"
        if names & REQUIRED_LOGIN_COOKIES:
            return "logged_in"
        return "anonymous"
