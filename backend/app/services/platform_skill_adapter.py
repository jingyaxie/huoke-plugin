from __future__ import annotations

from typing import Any

from app.schemas.crawl_cache import CacheMeta
from app.services.platform_skill_map import keyword_skill_for_platform
from app.services.skill_runner_service import SkillRunnerService


def keyword_skill_id(platform: str) -> str:
    return keyword_skill_for_platform(platform)


class PlatformSkillAdapter:
    """REST 平台工具路由 → SkillRunner 适配层。"""

    def __init__(self, runner: SkillRunnerService) -> None:
        self.runner = runner
        self.platform = runner.platform
        self.tenant_id = runner.tenant_id
        self.account_id = runner.account_id

    async def search(self, payload: Any) -> tuple[dict[str, Any], str | None, CacheMeta | None]:
        result = await self.runner.execute(
            "search-content",
            {
                "keyword": payload.keyword,
                "limit": payload.limit,
                "show_browser": payload.show_browser,
                "ui_search_only": bool(getattr(payload, "ui_search_only", False) or payload.show_browser),
                "days": getattr(payload, "days", None),
                "region": getattr(payload, "region", None),
                "force_refresh": payload.force_refresh,
                "cache_ttl_hours": payload.cache_ttl_hours,
            },
        )
        if result.get("error"):
            return {"videos": [], "diagnostic": result.get("error")}, None, None
        inner = result.get("result") or result
        videos = inner.get("videos") or inner.get("notes") or inner.get("videos_preview") or []
        return {
            "keyword": payload.keyword,
            "search_keyword": inner.get("search_keyword") or payload.keyword,
            "region": getattr(payload, "region", None),
            "days": getattr(payload, "days", None),
            "video_count": inner.get("video_count", len(videos)),
            "note_count": inner.get("note_count", len(videos)),
            "capture_method": inner.get("capture_method"),
            "videos": videos,
            "notes": videos,
            "diagnostic": inner.get("diagnostic"),
        }, inner.get("output_file"), None

    async def profile_videos(self, payload: Any) -> tuple[dict[str, Any], str | None, CacheMeta | None]:
        result = await self.runner.execute(
            "profile-url-videos",
            {
                "profile_url": payload.profile_url,
                "limit": payload.limit,
                "show_browser": payload.show_browser,
                "days": getattr(payload, "days", None),
                "video_publish_days": getattr(payload, "video_publish_days", None),
                "force_refresh": payload.force_refresh,
                "cache_ttl_hours": payload.cache_ttl_hours,
            },
            headless=not bool(payload.show_browser),
            timeout_seconds=300,
        )
        if result.get("error"):
            return {"videos": [], "diagnostic": result.get("error")}, None, None
        inner = result.get("result") or result
        videos = inner.get("videos") or inner.get("videos_preview") or []
        return {
            "profile_url": inner.get("profile_url") or payload.profile_url,
            "sec_uid": inner.get("sec_uid"),
            "priority_vid": inner.get("priority_vid"),
            "video_count": inner.get("video_count", len(videos)),
            "capture_method": inner.get("capture_method"),
            "videos": videos,
            "diagnostic": inner.get("diagnostic"),
        }, inner.get("output_file"), None

    async def crawl_content_comments(self, payload: Any) -> tuple[dict[str, Any], str | None, CacheMeta | None]:
        url = getattr(payload, "video_url", None) or getattr(payload, "note_url", None)
        result = await self.runner.execute(
            "content-comments",
            {
                "video_url": url,
                "note_url": url,
                "show_browser": payload.show_browser,
                "force_refresh": payload.force_refresh,
                "cache_ttl_hours": payload.cache_ttl_hours,
            },
        )
        inner = result.get("result") or result
        comments = inner.get("comments") or inner.get("comments_preview") or []
        preview = comments[:20]
        return {
            "aweme_id": inner.get("aweme_id"),
            "note_id": inner.get("note_id"),
            "video_url": inner.get("video_url") or inner.get("note_url") or url,
            "note_url": inner.get("note_url") or inner.get("video_url") or url,
            "total_comments_captured": inner.get("total_comments_captured", inner.get("comments_count", 0)),
            "api_total_top_comments": inner.get("api_total_top_comments", 0),
            "capture_method": inner.get("capture_method"),
            "comments_preview": preview,
            "comments_total_in_response": len(preview),
            "warning": inner.get("warning"),
        }, inner.get("output_file"), None

    async def crawl_keyword_comments(self, payload: Any) -> tuple[dict[str, Any], str | None, CacheMeta | None]:
        skill_id = keyword_skill_for_platform(self.platform)
        show_browser = bool(getattr(payload, "show_browser", True))
        result = await self.runner.execute(
            skill_id,
            {
                "keyword": payload.keyword,
                "content_limit": payload.limit,
                "limit": payload.limit,
                "days": payload.days,
                "region": getattr(payload, "region", None),
                "show_browser": show_browser,
                "guest_mode": getattr(payload, "guest_mode", False),
                "force_refresh": payload.force_refresh,
                "cache_ttl_hours": payload.cache_ttl_hours,
            },
            headless=False if show_browser else True,
            timeout_seconds=600,
        )
        results = result.get("results") or []
        outputs = result.get("output_files") or []
        items = []
        for row, path in zip(results, outputs, strict=False):
            if not isinstance(row, dict):
                continue
            items.append(
                {
                    "aweme_id": row.get("aweme_id"),
                    "note_id": row.get("note_id") or row.get("content_id"),
                    "video_url": row.get("video_url") or row.get("note_url"),
                    "note_url": row.get("note_url") or row.get("video_url"),
                    "total_comments_captured": row.get("total_comments_captured", 0),
                    "api_total_top_comments": row.get("api_total_top_comments", 0),
                    "report_file": str(path),
                }
            )
        return {
            "keyword": payload.keyword,
            "videos_found": len(results),
            "notes_found": len(results),
            "guest_mode": result.get("guest_mode", getattr(payload, "guest_mode", False)),
            "session_mode": result.get("session_mode", "logged_in"),
            "items": items,
        }, result.get("diagnostic"), None

    async def follow_user(self, payload: Any) -> dict[str, Any]:
        params = {
            "user_id": getattr(payload, "user_id", None),
            "sec_uid": getattr(payload, "sec_uid", None),
            "username": getattr(payload, "username", None) or "",
            "show_browser": payload.show_browser,
        }
        return await self.runner.execute("follow-user", params)

    async def unfollow_user(self, payload: Any) -> dict[str, Any]:
        params = {
            "user_id": getattr(payload, "user_id", None),
            "sec_uid": getattr(payload, "sec_uid", None),
            "username": getattr(payload, "username", None) or "",
            "show_browser": payload.show_browser,
        }
        return await self.runner.execute("unfollow-user", params)

    async def send_message(self, payload: Any) -> dict[str, Any]:
        params = {
            "user_id": getattr(payload, "user_id", None),
            "sec_uid": getattr(payload, "sec_uid", None),
            "username": getattr(payload, "username", None) or "",
            "message": payload.message,
            "show_browser": payload.show_browser,
        }
        return await self.runner.execute("send-dm", params)
