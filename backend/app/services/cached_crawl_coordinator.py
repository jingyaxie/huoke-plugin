from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.crawl_cache import DEFAULT_CACHE_TTL_HOURS, CacheMeta
from app.services.comment_store_service import CommentStoreService, extract_content_id
from app.services.crawl_cache_service import CrawlCacheService, build_params_hash


@dataclass
class CachedCrawlResult:
    payload: dict[str, Any]
    output: Path | None
    meta: CacheMeta


class CachedCrawlCoordinator:
    """统一缓存协调层：所有抓取类接口经此层读写缓存与增量合并。"""

    _TASK_SCOPED_SESSION_META_KEYS = frozenset(
        {"watched_content_ids", "watched_job_id", "crawl_search_exhausted"}
    )

    @classmethod
    def _sanitize_task_scoped_session_meta(cls, session_meta: dict[str, Any] | None) -> dict[str, Any]:
        meta = dict(session_meta) if isinstance(session_meta, dict) else {}
        for key in cls._TASK_SCOPED_SESSION_META_KEYS:
            meta.pop(key, None)
        meta["cache_replay"] = True
        return meta

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        tenant_id: str,
        platform: str,
        account_id: str = "default",
    ) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.account_id = account_id
        self.cache = CrawlCacheService(
            session,
            settings,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
        )
        self.comment_store = CommentStoreService(session, settings, tenant_id)

    def _search_file_path(self, params: dict[str, Any]) -> Path:
        digest = build_params_hash(params)
        path = self.settings.report_output_dir / f"search_{self.platform}_{self.tenant_id}_{digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _stale_fallback(
        self,
        operation: str,
        params: dict[str, Any],
        exc: Exception,
    ) -> CachedCrawlResult | None:
        stale = self.cache.lookup_stale(operation, params)
        if stale is None:
            return None
        meta = stale.meta.model_copy(
            update={"stale_fallback": True, "refresh_error": str(exc)[:500]},
        )
        payload = self.cache.attach_meta(stale.payload, meta)
        return CachedCrawlResult(payload, stale.file_path, meta)

    def _stale_keyword_comments_fallback(
        self,
        params: dict[str, Any],
        exc: Exception,
    ) -> tuple[list[dict[str, Any]], list[Path], str | None, dict[str, Any], CacheMeta] | None:
        result = self._stale_fallback("keyword_comments", params, exc)
        if result is None:
            return None
        payload = result.payload
        outputs = [Path(p) for p in (payload.get("output_files") or []) if p]
        return (
            payload.get("items") or [],
            outputs,
            payload.get("diagnostic"),
            self._sanitize_task_scoped_session_meta(payload.get("session_meta")),
            result.meta,
        )

    async def cached_search_videos(
        self,
        fetcher,
        *,
        keyword: str,
        limit: int,
        show_browser: bool,
        days: int | None,
        region: str | None,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        extra_fetch_kwargs: dict | None = None,
    ) -> CachedCrawlResult:
        params = {
            "keyword": keyword,
            "limit": limit,
            "show_browser": show_browser,
            "days": days,
            "region": region,
        }
        if extra_fetch_kwargs:
            params.update(extra_fetch_kwargs)
        cached = self.cache.lookup(
            "search_videos",
            params,
            force_refresh=force_refresh,
            cache_ttl_hours=cache_ttl_hours,
        )
        if cached is not None:
            return CachedCrawlResult(cached.payload, cached.file_path, cached.meta)

        fetch_kwargs = {
            "show_browser": show_browser,
            "days": days,
            "region": region,
        }
        if extra_fetch_kwargs:
            fetch_kwargs.update(extra_fetch_kwargs)
        try:
            payload, _output = await fetcher(
                keyword=keyword,
                limit=limit,
                **fetch_kwargs,
            )
        except Exception as exc:
            fallback = self._stale_fallback("search_videos", params, exc)
            if fallback is not None:
                return fallback
            raise
        canonical = self._search_file_path(params)
        canonical.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = self.cache.store(
            "search_videos",
            params,
            payload,
            file_path=canonical,
            cache_ttl_hours=cache_ttl_hours,
        )
        self.session.commit()
        return CachedCrawlResult(self.cache.attach_meta(payload, meta), canonical, meta)

    async def cached_video_comments(
        self,
        fetcher,
        *,
        content_url: str,
        max_comments: int,
        show_browser: bool,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        extra_fetch_kwargs: dict | None = None,
    ) -> CachedCrawlResult:
        params = {
            "content_url": content_url,
            "max_comments": max_comments,
            "show_browser": show_browser,
        }
        if extra_fetch_kwargs:
            params.update(extra_fetch_kwargs)
        cached = self.cache.lookup(
            "video_comments",
            params,
            force_refresh=force_refresh,
            cache_ttl_hours=cache_ttl_hours,
        )
        if cached is not None:
            return CachedCrawlResult(cached.payload, cached.file_path, cached.meta)

        fetch_kwargs = {
            "show_browser": show_browser,
            "max_comments": max_comments,
        }
        if extra_fetch_kwargs:
            fetch_kwargs.update(extra_fetch_kwargs)
        try:
            fetched_payload, _output = await fetcher(content_url, **fetch_kwargs)
        except Exception as exc:
            fallback = self._stale_fallback("video_comments", params, exc)
            if fallback is not None:
                return fallback
            raise
        content_id = extract_content_id(self.platform, content_url, fetched_payload)
        if not content_id:
            meta = self.cache.store(
                "video_comments",
                params,
                fetched_payload,
                file_path=_output,
                cache_ttl_hours=cache_ttl_hours,
            )
            self.session.commit()
            return CachedCrawlResult(self.cache.attach_meta(fetched_payload, meta), _output, meta)

        merged, canonical, stats = self.comment_store.merge_and_persist(
            platform=self.platform,
            content_id=content_id,
            content_url=content_url,
            fetched_payload=fetched_payload,
            max_comments=max_comments,
        )
        meta = self.cache.store(
            "video_comments",
            params,
            merged,
            file_path=canonical,
            cache_ttl_hours=cache_ttl_hours,
            incremental_merge=True,
            new_comments_added=stats.new_comments_added,
            updated_comments=stats.updated_comments,
        )
        self.session.commit()
        return CachedCrawlResult(self.cache.attach_meta(merged, meta), canonical, meta)

    async def cached_keyword_comments(
        self,
        fetcher,
        *,
        keyword: str,
        limit: int,
        max_comments: int,
        show_browser: bool,
        guest_mode: bool,
        days: int,
        region: str | None,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        extra_fetch_kwargs: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[Path], str | None, dict[str, Any], CacheMeta]:
        extra_fetch_kwargs = extra_fetch_kwargs or {}
        if extra_fetch_kwargs.get("ui_first") or extra_fetch_kwargs.get("ui_search_only"):
            force_refresh = True
        capture_mode = str(extra_fetch_kwargs.get("capture_mode") or "").strip().lower()
        if capture_mode in {"ui_first", "ui_passive", "passive_api"}:
            force_refresh = True
        params = {
            "keyword": keyword,
            "limit": limit,
            "max_comments": max_comments,
            "show_browser": show_browser,
            "guest_mode": guest_mode,
            "days": days,
            "region": region,
            **extra_fetch_kwargs,
        }
        cached = self.cache.lookup(
            "keyword_comments",
            params,
            force_refresh=force_refresh,
            cache_ttl_hours=cache_ttl_hours,
        )
        if cached is not None:
            payload = cached.payload
            diagnostic = str(payload.get("diagnostic") or "")
            if any(token in diagnostic for token in ("验证码", "verify_check", "人机验证", "风控")):
                cached = None
            else:
                items = payload.get("items") or []
                if items and all(int(row.get("total_comments_captured") or 0) <= 0 for row in items if isinstance(row, dict)):
                    cached = None
                else:
                    outputs = [Path(p) for p in (payload.get("output_files") or []) if p]
                    return (
                        items,
                        outputs,
                        payload.get("diagnostic"),
                        self._sanitize_task_scoped_session_meta(payload.get("session_meta")),
                        cached.meta,
                    )

        try:
            results, outputs, diagnostic, session_meta = await fetcher(
                keyword=keyword,
                limit=limit,
                max_comments=max_comments,
                show_browser=show_browser,
                guest_mode=guest_mode,
                days=days,
                region=region,
                **extra_fetch_kwargs,
            )
        except Exception as exc:
            fallback = self._stale_keyword_comments_fallback(params, exc)
            if fallback is not None:
                return fallback
            raise

        merged_items: list[dict[str, Any]] = []
        merged_outputs: list[Path] = []
        total_new = 0
        total_updated = 0

        for result, output in zip(results, outputs, strict=False):
            content_url = result.get("video_url") or result.get("note_url") or ""
            content_id = extract_content_id(self.platform, content_url, result)
            if content_id:
                merged, canonical, stats = self.comment_store.merge_and_persist(
                    platform=self.platform,
                    content_id=content_id,
                    content_url=content_url,
                    fetched_payload=result,
                    max_comments=max_comments,
                )
                total_new += stats.new_comments_added
                total_updated += stats.updated_comments
                merged_items.append(merged)
                merged_outputs.append(canonical)
            else:
                merged_items.append(result)
                merged_outputs.append(output)

        payload = {
            "keyword": keyword,
            "items": merged_items,
            "output_files": [str(p) for p in merged_outputs],
            "diagnostic": diagnostic,
            "session_meta": session_meta,
            "videos_found": len(merged_items),
        }
        meta = self.cache.store(
            "keyword_comments",
            params,
            payload,
            cache_ttl_hours=cache_ttl_hours,
            incremental_merge=True,
            new_comments_added=total_new,
            updated_comments=total_updated,
        )
        self.session.commit()
        return merged_items, merged_outputs, diagnostic, session_meta, meta

    async def cached_dashboard(
        self,
        fetcher,
        *,
        show_browser: bool,
        works_limit: int,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> CachedCrawlResult:
        params = {"show_browser": show_browser, "works_limit": works_limit}
        cached = self.cache.lookup(
            "dashboard",
            params,
            force_refresh=force_refresh,
            cache_ttl_hours=cache_ttl_hours,
        )
        if cached is not None:
            return CachedCrawlResult(cached.payload, cached.file_path, cached.meta)

        try:
            payload, output = await fetcher(show_browser=show_browser, works_limit=works_limit)
        except Exception as exc:
            fallback = self._stale_fallback("dashboard", params, exc)
            if fallback is not None:
                return fallback
            raise
        meta = self.cache.store(
            "dashboard",
            params,
            payload,
            file_path=output,
            cache_ttl_hours=cache_ttl_hours,
        )
        self.session.commit()
        return CachedCrawlResult(self.cache.attach_meta(payload, meta), output, meta)

    def cached_pipeline_lookup(
        self,
        *,
        keyword: str,
        platforms: list[str],
        video_limit: int,
        days: int = 3,
        video_publish_days: int | None = None,
        region: str | None = None,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> CachedCrawlResult | None:
        params = {
            "keyword": keyword,
            "platforms": platforms,
            "video_limit": video_limit,
            "days": days,
            "video_publish_days": video_publish_days,
            "region": region,
        }
        cached = self.cache.lookup(
            "pipeline_keyword_comments",
            params,
            force_refresh=force_refresh,
            cache_ttl_hours=cache_ttl_hours,
        )
        if cached is None:
            return None
        return CachedCrawlResult(cached.payload, cached.file_path, cached.meta)

    def store_pipeline_result(
        self,
        *,
        keyword: str,
        platforms: list[str],
        video_limit: int,
        days: int = 3,
        video_publish_days: int | None = None,
        region: str | None = None,
        payload: dict[str, Any],
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> CacheMeta:
        params = {
            "keyword": keyword,
            "platforms": platforms,
            "video_limit": video_limit,
            "days": days,
            "video_publish_days": video_publish_days,
            "region": region,
        }
        meta = self.cache.store(
            "pipeline_keyword_comments",
            params,
            payload,
            cache_ttl_hours=cache_ttl_hours,
        )
        self.session.commit()
        return meta
