from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.comment_tool import DouyinCommentTool
from app.platforms.douyin.js_constants import DEFAULT_MAX_COMMENTS, PLATFORM, _extract_aweme_id
from app.platforms.douyin.profile_videos import DouyinProfileVideosTool, parse_profile_input_url
from app.platforms.douyin.search import DouyinSearchTool
from app.platforms.search_filters import SearchFilterOptions
from app.platforms.douyin.session import DouyinSessionStore, USER_LOGIN_MARKERS
from app.platforms.douyin.crawler import DouyinCrawler
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

# 从此模块继续导出常量
from app.platforms.douyin.js_constants import (  # noqa: F401
    COMMENT_PATH,
    DEFAULT_MAX_COMMENTS,
    DROP_QUERY_KEYS,
    PLATFORM,
    SEARCH_ITEM_PATH,
    SEARCH_SINGLE_PATH,
)


class DouyinCommentCrawler:
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
        self.store = store or DouyinSessionStore(settings)
        self._search = DouyinSearchTool(settings, tenant_id, self.store, account_id=account_id)
        self._profile_videos = DouyinProfileVideosTool(settings, tenant_id, self.store, account_id=account_id)
        self._comments = DouyinCommentTool(settings, tenant_id, self.store, account_id=account_id)

    @property
    def entry_url(self) -> str:
        return self._search.entry_url

    @property
    def js_warmup_urls(self) -> tuple[str, ...]:
        return self._search.js_warmup_urls

    async def crawl_note_comments(self, *args, **kwargs):
        return await self._comments.crawl_note_comments(*args, **kwargs)

    async def crawl_video_comments(self, *args, **kwargs):
        return await self._comments.crawl_video_comments(*args, **kwargs)

    async def search_videos(self, *args, **kwargs):
        return await self._search.search_videos(*args, **kwargs)

    async def search_videos_by_keyword(self, *args, **kwargs):
        return await self._search.search_videos_by_keyword(*args, **kwargs)

    async def collect_profile_videos(self, *args, **kwargs):
        return await self._profile_videos.collect_profile_videos(*args, **kwargs)

    async def crawl_profile_comments(
        self,
        profile_url: str,
        limit: int = 5,
        show_browser: bool = False,
        days: int | None = None,
        comment_days: int | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        *,
        existing_page=None,
        video_publish_days: int | None = None,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        publish_days = video_publish_days if video_publish_days is not None else days
        resolved_headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        session_meta = self._build_session_meta(guest_mode=False)

        async def _run(page) -> tuple[list[dict], list[Path], str | None]:
            return await self._crawl_profile_comments_on_page(
                page,
                profile_url=profile_url,
                limit=limit,
                days=publish_days,
                comment_days=comment_days,
                max_comments=max_comments,
                session_meta=session_meta,
            )

        if existing_page is not None and not existing_page.is_closed():
            results, files, diagnostic = await _run(existing_page)
            session_meta["session_mode"] = await self._detect_session_mode_from_page(existing_page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta

        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, page):
            results, files, diagnostic = await _run(page)
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta

    async def _crawl_profile_comments_on_page(
        self,
        page,
        *,
        profile_url: str,
        limit: int,
        days: int | None,
        comment_days: int | None,
        max_comments: int,
        session_meta: dict | None = None,
    ) -> tuple[list[dict], list[Path], str | None]:
        from app.platforms.douyin.video_comments_passive import _days_cutoff_ts, _filter_comments_by_days

        captured_api_urls: list[str] = []
        videos, diagnostic, _capture = await self._profile_videos.collect_videos_on_page(
            page,
            profile_url=profile_url,
            limit=limit,
            days=days,
            captured_api_urls=captured_api_urls,
        )

        if not videos:
            return [], [], diagnostic or "主页未采集到可抓取评论的视频"

        from app.platforms.douyin.video_comments_passive import crawl_video_url_comments

        parsed = parse_profile_input_url(profile_url)
        results: list[dict] = []
        files: list[Path] = []
        if session_meta is not None:
            session_meta["videos_processed"] = 0

        for video in videos[:limit]:
            url = str(video.get("video_url") or "")
            aweme_id = _extract_aweme_id(url) or str(video.get("aweme_id") or "")
            if not aweme_id:
                continue
            payload, _persist_meta = await crawl_video_url_comments(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                account_id=self.account_id,
                video_url=url,
                max_comments=max_comments,
                days=comment_days,
                raw_params={"profile_url": profile_url, "days": comment_days},
            )
            if comment_days is not None and payload.get("comments"):
                cutoff = _days_cutoff_ts(comment_days)
                comments_map = {
                    str(row.get("comment_id")): row
                    for row in (payload.get("comments") or [])
                    if row.get("comment_id")
                }
                filtered = _filter_comments_by_days(
                    comments_map,
                    cutoff_ts=cutoff,
                    max_comments=max_comments,
                )
                api_total = int(payload.get("api_total_top_comments") or len(comments_map) or 0)
                payload["comments"] = filtered
                payload["total_comments_captured"] = len(filtered)
                payload["top_comments_captured"] = len(
                    [row for row in filtered if not row.get("parent_comment_id")]
                )
                payload["comment_days"] = comment_days
                if not filtered and api_total > 0:
                    payload["warning"] = (
                        f"接口返回 {api_total} 条评论，近 {comment_days} 天时间窗内 0 条"
                    )
            payload["platform"] = PLATFORM
            payload["profile_context"] = {
                "profile_url": parsed.get("profile_url") or profile_url,
                "sec_uid": parsed.get("sec_uid") or video.get("sec_uid") or "",
                "video_publish_days": days,
            }
            if session_meta:
                payload["profile_context"].update(
                    {
                        "guest_mode": session_meta.get("guest_mode", False),
                        "session_mode": session_meta.get("session_mode"),
                    }
                )
            output = (
                self.settings.report_output_dir
                / f"comments_{self.platform}_{self.tenant_id}_{aweme_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(payload)
            files.append(output)
            if session_meta is not None:
                session_meta["videos_processed"] = int(session_meta.get("videos_processed") or 0) + 1

        watched_ids = [str(v.get("aweme_id") or "") for v in videos if v.get("aweme_id")]
        if session_meta is not None and watched_ids:
            session_meta["watched_content_ids"] = watched_ids[:500]
        return results, files, diagnostic

    async def _fetch_video_comments(self, *args, **kwargs):
        return await self._comments._fetch_video_comments(*args, **kwargs)

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int | None = None,
        comment_days: int | None = None,
        region: str | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        *,
        guest_mode: bool = False,
        existing_page=None,
        manual_search: bool = False,
        search_url_first: bool = False,
        ui_search_only: bool = False,
        ui_first: bool = False,
        ui_flow_context: dict | None = None,
        capture_mode: str | None = None,
        **_,
    ) -> tuple[list[dict], list[Path], str | None, dict]:
        mode = str(capture_mode or "").strip().lower()
        if mode in {"ui_first", "ui_passive", "passive_api"} and not ui_first:
            ui_first = True
        if mode and isinstance(ui_flow_context, dict):
            ui_flow_context.setdefault("capture_mode", capture_mode)
        elif mode:
            ui_flow_context = {"capture_mode": capture_mode, **(ui_flow_context or {})}
        if guest_mode and show_browser:
            raise ValueError("guest_mode 与 show_browser 不能同时使用，游客态请使用无头模式")
        if not guest_mode:
            require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if ui_search_only and existing_page is None:
            return (
                [],
                [],
                "UI 搜索需要任务浏览器会话（禁止 PlaywrightPool 临时窗口）",
                self._build_session_meta(guest_mode=guest_mode),
            )
        resolved_headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        session_meta = self._build_session_meta(guest_mode=guest_mode)
        capture_days = comment_days if comment_days is not None else days
        if existing_page is not None:
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                existing_page,
                keyword=keyword,
                limit=limit,
                manual_search=manual_search,
                headless=resolved_headless,
                days=days,
                comment_days=capture_days,
                region=region,
                max_comments=max_comments,
                from_existing=True,
                session_meta=session_meta,
                search_url_first=search_url_first,
                ui_search_only=ui_search_only,
                ui_first=ui_first,
                ui_flow_context=ui_flow_context,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(existing_page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta

        crawler = DouyinCrawler(self.settings, self.tenant_id, self.store)
        session = DouyinCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
        if show_browser and not session and existing_page is None and manual_search:
            await crawler.start_interactive_login_session()
            session = DouyinCrawler.get_interactive_session(PLATFORM, self.tenant_id, self.account_id)
        if session:
            page = session["page"]
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                page,
                keyword=keyword,
                limit=limit,
                manual_search=manual_search,
                headless=resolved_headless,
                days=days,
                comment_days=capture_days,
                region=region,
                max_comments=max_comments,
                from_existing=True,
                session_meta=session_meta,
                search_url_first=search_url_first,
                ui_search_only=ui_search_only,
                ui_first=ui_first,
                ui_flow_context=ui_flow_context,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta

        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, page):
            results, files, diagnostic = await self._crawl_keyword_comments_on_page(
                page,
                keyword=keyword,
                limit=limit,
                manual_search=manual_search,
                headless=resolved_headless,
                days=days,
                comment_days=capture_days,
                region=region,
                max_comments=max_comments,
                from_existing=False,
                session_meta=session_meta,
                search_url_first=search_url_first,
                ui_search_only=ui_search_only,
                ui_first=ui_first,
                ui_flow_context=ui_flow_context,
            )
            session_meta["session_mode"] = await self._detect_session_mode_from_page(page)
            return results, files, self._apply_session_diagnostic(diagnostic, session_meta), session_meta


    def _build_session_meta(self, *, guest_mode: bool) -> dict:
        state = self.store.load(self.tenant_id, self.account_id)
        if guest_mode:
            mode = "guest"
        elif self.store.is_user_logged_in(state):
            mode = "logged_in"
        elif self.store.is_ready(state):
            mode = "guest"
        else:
            mode = "anonymous"
        return {"guest_mode": guest_mode, "session_mode": mode}

    @staticmethod
    def _apply_session_diagnostic(diagnostic: str | None, session_meta: dict) -> str | None:
        mode = session_meta.get("session_mode")
        if mode not in {"guest", "anonymous"}:
            return diagnostic
        label = "游客态" if mode == "guest" else "匿名态"
        if not diagnostic:
            return f"当前为{label}，结果可能不完整"
        if label in diagnostic:
            return diagnostic
        return f"{diagnostic}（{label}）"


    async def _detect_session_mode_from_page(self, page) -> str:
        try:
            names = {c.get("name") for c in await page.context.cookies() if c.get("name")}
        except Exception:
            return "anonymous"
        if names & USER_LOGIN_MARKERS:
            return "logged_in"
        if names & DouyinSessionStore.REQUIRED_LOGIN_COOKIES:
            return "guest"
        return "anonymous"


    async def _crawl_keyword_comments_on_page(
        self,
        page,
        *,
        keyword: str,
        limit: int,
        manual_search: bool,
        headless: bool,
        days: int | None,
        comment_days: int | None,
        region: str | None,
        max_comments: int,
        from_existing: bool,
        session_meta: dict | None = None,
        search_url_first: bool = False,
        ui_search_only: bool = False,
        ui_first: bool = False,
        ui_flow_context: dict | None = None,
    ) -> tuple[list[dict], list[Path], str | None]:
        captured_api_urls: list[str] = []

        def on_response(resp):
            if "/aweme/v1/web/" in resp.url:
                captured_api_urls.append(resp.url)

        watched: set[str] = set()
        watched_job_id = ""
        if isinstance(ui_flow_context, dict):
            watched_job_id = str(
                ui_flow_context.get("job_id")
                or ui_flow_context.get("task_id")
                or ""
            ).strip()
            supervisor_state = ui_flow_context.get("supervisor_state")
            if not isinstance(supervisor_state, dict):
                supervisor_state = {}
            if watched_job_id:
                stored_job = str(supervisor_state.get("job_id") or "").strip()
                if stored_job and stored_job != watched_job_id:
                    supervisor_state = {}
            for raw in ui_flow_context.get("watched_content_ids") or []:
                token = str(raw or "").strip()
                if token:
                    watched.add(token)
            if isinstance(supervisor_state.get("watched_content_ids"), list):
                stored_job = str(supervisor_state.get("job_id") or "").strip()
                if not stored_job or not watched_job_id or stored_job == watched_job_id:
                    for raw in supervisor_state.get("watched_content_ids") or []:
                        token = str(raw or "").strip()
                        if token:
                            watched.add(token)

        page.on("response", on_response)
        try:
            video_urls, diagnostic, _template_url = await self._search.keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured_api_urls,
                region=region,
                days=days,
                headless=headless,
                manual_search=manual_search,
                search_url_first=search_url_first,
                ui_search_only=ui_search_only,
                watched_skip=len(watched),
            )
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass
        page_url = page.url or ""
        search_url = page_url if ("/search/" in page_url or "/jingxuan/search/" in page_url) else ""
        if video_urls:
            if session_meta is not None:
                session_meta["discovered_video_urls"] = list(video_urls)
                session_meta["discovered_video_count"] = len(video_urls)
                session_meta["search_succeeded"] = True
                if search_url:
                    session_meta["search_url"] = search_url
        filters = SearchFilterOptions.from_params(keyword=keyword, region=region, days=days)
        results: list[dict] = []
        files: list[Path] = []
        fresh_urls: list[str] = []
        for url in video_urls:
            aweme_id = _extract_aweme_id(url)
            if aweme_id and aweme_id in watched:
                continue
            fresh_urls.append(url)
            if len(fresh_urls) >= limit:
                break
        if session_meta is not None:
            session_meta["videos_processed"] = 0
            if not fresh_urls and watched:
                session_meta["crawl_search_exhausted"] = True
                diagnostic = diagnostic or "当前搜索列表已无新视频可浏览，请更换关键词或放宽匹配规则"
        for url in fresh_urls:
            aweme_id = _extract_aweme_id(url)
            if aweme_id:
                watched.add(aweme_id)
            from app.platforms.douyin.video_comments_passive import crawl_video_url_comments

            db_session = None
            if isinstance(ui_flow_context, dict):
                db_session = ui_flow_context.get("db_session")
            raw_params: dict = {"days": comment_days, "keyword": keyword, "region": region}
            if isinstance(ui_flow_context, dict) and ui_flow_context.get("capture_mode"):
                raw_params["capture_mode"] = ui_flow_context.get("capture_mode")
            payload, persist_meta = await crawl_video_url_comments(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                account_id=self.account_id,
                video_url=url,
                max_comments=max_comments,
                days=comment_days,
                raw_params=raw_params,
                db_session=db_session,
            )
            if persist_meta and session_meta is not None:
                session_meta["comments_persisted"] = int(
                    session_meta.get("comments_persisted") or 0
                ) + int(persist_meta.get("persisted") or 0)
            payload["platform"] = PLATFORM
            ctx = {
                "keyword": keyword,
                "search_keyword": filters.composed_keyword(),
                "days": comment_days,
                "region": region,
            }
            if session_meta:
                ctx.update(
                    {
                        "guest_mode": session_meta.get("guest_mode", False),
                        "session_mode": session_meta.get("session_mode"),
                    }
                )
            payload["keyword_context"] = ctx
            output = (
                self.settings.report_output_dir
                / f"comments_{self.platform}_{self.tenant_id}_{aweme_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(payload)
            files.append(output)
            if session_meta is not None:
                session_meta["videos_processed"] = int(session_meta.get("videos_processed") or 0) + 1
        if session_meta is not None:
            session_meta["watched_content_ids"] = sorted(watched)[-500:]
            if watched_job_id:
                session_meta["watched_job_id"] = watched_job_id
        return results, files, diagnostic
