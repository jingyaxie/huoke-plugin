from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.platforms.registry import get_comment_crawler
from app.platforms.types import normalize_platform
from app.schemas.crawl_cache import DEFAULT_CACHE_TTL_HOURS, CacheMeta
from app.services.cached_crawl_coordinator import CachedCrawlCoordinator


class CommentCrawlerService:
    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        platform: str | None = None,
        account_id: str = "default",
        session: Session | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.platform = normalize_platform(platform or self.settings.default_platform)
        self.account_id = account_id
        self.session = session
        self._backend = get_comment_crawler(
            self.settings, self.platform, self.tenant_id, account_id=self.account_id
        )
        self._coordinator = (
            CachedCrawlCoordinator(
                session,
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                account_id=self.account_id,
            )
            if session is not None
            else None
        )

    async def crawl_video_comments(
        self,
        video_url: str,
        show_browser: bool = False,
        *,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        days: int | None = None,
        max_comments: int = 200,
        ui_passive: bool = False,
        existing_page=None,
        raw_params: dict | None = None,
    ) -> tuple[dict, Path, CacheMeta | None]:
        fetch_kwargs = {
            "show_browser": show_browser,
            "max_comments": max_comments,
            "days": days,
            "ui_passive": ui_passive,
            "raw_params": raw_params,
            "page": existing_page,
            "db_session": self.session,
        }
        if self._coordinator is not None:
            result = await self._coordinator.cached_video_comments(
                self._backend.crawl_note_comments,
                content_url=video_url,
                max_comments=max_comments,
                show_browser=show_browser,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
                extra_fetch_kwargs={
                    k: v
                    for k, v in fetch_kwargs.items()
                    if k not in {"show_browser", "max_comments"} and v is not None
                },
            )
            payload = result.payload
            if "video_url" not in payload and payload.get("note_url"):
                payload["video_url"] = payload["note_url"]
            return payload, result.output or Path(""), result.meta

        payload, output = await self._backend.crawl_note_comments(video_url, **fetch_kwargs)
        if "video_url" not in payload and payload.get("note_url"):
            payload["video_url"] = payload["note_url"]
        return payload, output, None

    async def crawl_keyword_comments(
        self,
        keyword: str,
        limit: int = 3,
        show_browser: bool = False,
        days: int | None = None,
        comment_days: int | None = None,
        region: str | None = None,
        *,
        guest_mode: bool = False,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        existing_page=None,
        manual_search: bool = False,
        search_url_first: bool = False,
        ui_search_only: bool = False,
        ui_first: bool = False,
        max_comments: int | None = None,
        ui_flow_context: dict | None = None,
        capture_mode: str | None = None,
    ) -> tuple[list[dict], list[Path], str | None, dict, CacheMeta | None]:
        if guest_mode and self.platform != "douyin":
            raise ValueError("guest_mode 仅支持抖音平台")

        crawl_kwargs: dict = {
            "search_url_first": search_url_first,
            "ui_search_only": ui_search_only,
            "ui_first": ui_first,
            "manual_search": manual_search,
            "existing_page": existing_page,
        }
        if capture_mode:
            crawl_kwargs["capture_mode"] = capture_mode
        if max_comments is not None:
            crawl_kwargs["max_comments"] = max_comments
        if comment_days is not None:
            crawl_kwargs["comment_days"] = comment_days
        if ui_flow_context is not None:
            crawl_kwargs["ui_flow_context"] = ui_flow_context

        if self._coordinator is not None:
            effective_days = days if days is not None else comment_days
            if effective_days is None:
                effective_days = 3
            items, outputs, diagnostic, session_meta, meta = await self._coordinator.cached_keyword_comments(
                self._backend.crawl_keyword_comments,
                keyword=keyword,
                limit=limit,
                max_comments=max_comments or 200,
                show_browser=show_browser,
                guest_mode=guest_mode,
                days=effective_days,
                region=region,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
                extra_fetch_kwargs=crawl_kwargs,
            )
            return items, outputs, diagnostic, session_meta, meta

        results, outputs, diagnostic, session_meta = await self._backend.crawl_keyword_comments(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
            guest_mode=guest_mode,
            **crawl_kwargs,
        )
        return results, outputs, diagnostic, session_meta, None

    async def search_videos(
        self,
        keyword: str,
        limit: int = 20,
        show_browser: bool = False,
        days: int | None = None,
        region: str | None = None,
        *,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        ui_search_only: bool = False,
        existing_page=None,
    ) -> tuple[dict, Path, CacheMeta | None]:
        backend = self._backend
        if not hasattr(backend, "search_videos"):
            raise NotImplementedError(f"平台 {self.platform} 暂不支持关键词视频搜索")

        fetch_kwargs = {"ui_search_only": ui_search_only or show_browser}
        if existing_page is not None:
            fetch_kwargs["existing_page"] = existing_page
        if self._coordinator is not None:
            result = await self._coordinator.cached_search_videos(
                backend.search_videos,
                keyword=keyword,
                limit=limit,
                show_browser=show_browser,
                days=days,
                region=region,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
                extra_fetch_kwargs=fetch_kwargs,
            )
            return result.payload, result.output or Path(""), result.meta

        payload, output = await backend.search_videos(
            keyword=keyword,
            limit=limit,
            show_browser=show_browser,
            days=days,
            region=region,
            **fetch_kwargs,
        )
        return payload, output, None

    async def collect_profile_videos(
        self,
        profile_url: str,
        limit: int = 20,
        show_browser: bool = False,
        days: int | None = None,
        *,
        existing_page=None,
    ) -> tuple[dict, Path, CacheMeta | None]:
        backend = self._backend
        if not hasattr(backend, "collect_profile_videos"):
            raise NotImplementedError(f"平台 {self.platform} 暂不支持主页 URL 视频采集")
        fetch_kwargs: dict = {}
        if existing_page is not None:
            fetch_kwargs["existing_page"] = existing_page
        payload, output = await backend.collect_profile_videos(
            profile_url=profile_url,
            limit=limit,
            show_browser=show_browser,
            days=days,
            **fetch_kwargs,
        )
        return payload, output, None

    async def crawl_profile_comments(
        self,
        profile_url: str,
        limit: int = 5,
        show_browser: bool = False,
        days: int = 3,
        comment_days: int | None = None,
        *,
        max_comments: int = 200,
        existing_page=None,
        video_publish_days: int | None = None,
    ) -> tuple[list[dict], list[Path], str | None, dict, CacheMeta | None]:
        backend = self._backend
        if not hasattr(backend, "crawl_profile_comments"):
            raise NotImplementedError(f"平台 {self.platform} 暂不支持主页 URL 批量抓评")
        crawl_kwargs: dict = {}
        if existing_page is not None:
            crawl_kwargs["existing_page"] = existing_page
        if video_publish_days is not None:
            crawl_kwargs["video_publish_days"] = video_publish_days
        if comment_days is not None:
            crawl_kwargs["comment_days"] = comment_days
        results, outputs, diagnostic, session_meta = await backend.crawl_profile_comments(
            profile_url=profile_url,
            limit=limit,
            show_browser=show_browser,
            days=days,
            max_comments=max_comments,
            **crawl_kwargs,
        )
        return results, outputs, diagnostic, session_meta, None
