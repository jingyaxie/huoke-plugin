from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.compat.envelope import CompatError
from app.services.compat.normalizers import comments_to_tikhub_douyin, videos_to_aweme_list
from app.services.compat.runtime import execute_skill

logger = logging.getLogger(__name__)


def _compat_show_browser(body: dict[str, Any]) -> bool:
    """流程测试或显式 debug 时打开可见浏览器；默认 headless 不影响正式获客。"""
    for key in ("headed", "show_browser", "debug"):
        val = body.get(key)
        if val is True or val == 1:
            return True
        if isinstance(val, str) and val.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _resolve_search_source(body: dict[str, Any], *, show_browser: bool) -> str:
    raw = str(body.get("source") or "auto").strip().lower()
    if raw in {"mobile_hook", "hook", "bridge"}:
        return "mobile_hook"
    if raw in {"playwright", "browser", "sidecar"}:
        return "playwright"
    if show_browser:
        return "playwright"
    return "auto"


async def fetch_video_search(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    keyword = str(body.get("keyword") or body.get("search_keyword") or "").strip()
    if not keyword:
        raise CompatError("缺少 keyword", code=400)
    limit = int(body.get("count") or body.get("limit") or 10)
    limit = max(1, min(limit, 20))
    show_browser = _compat_show_browser(body)
    source = _resolve_search_source(body, show_browser=show_browser)
    logger.info(
        "compat fetch_video_search keyword=%r limit=%s show_browser=%s source=%s headed_keys=%s",
        keyword,
        limit,
        show_browser,
        source,
        {k: body.get(k) for k in ("headed", "show_browser", "debug") if k in body},
    )
    result = await execute_skill(
        settings,
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        platform="douyin",
        skill_id="search-content",
        params={
            "keyword": keyword,
            "limit": limit,
            "show_browser": show_browser,
            "force_refresh": show_browser,
            "source": source,
        },
    )
    if result.get("error"):
        raise CompatError(str(result.get("error")), code=502)
    inner = result.get("result") or result
    videos = inner.get("videos") or inner.get("videos_preview") or []
    if not videos:
        raise CompatError(inner.get("diagnostic") or "未搜索到视频", code=404)
    return videos_to_aweme_list(videos)


async def fetch_video_comments(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    aweme_id = str(body.get("aweme_id") or "").strip()
    video_url = str(body.get("video_url") or body.get("share_url") or "").strip()
    if not video_url and aweme_id:
        video_url = f"https://www.douyin.com/video/{aweme_id}"
    if not video_url:
        raise CompatError("缺少 aweme_id 或 video_url", code=400)
    max_comments = int(body.get("count") or body.get("max_comments") or 200)
    result = await execute_skill(
        settings,
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        platform="douyin",
        skill_id="content-comments",
        params={
            "video_url": video_url,
            "max_comments": max_comments,
            "show_browser": False,
        },
    )
    if result.get("error"):
        raise CompatError(str(result.get("error")), code=502)
    inner = result.get("result") or result
    comments = inner.get("comments") or inner.get("comments_preview") or []
    cursor = int(body.get("cursor") or 0)
    has_more = 1 if len(comments) >= max_comments else 0
    return comments_to_tikhub_douyin(comments, cursor=cursor, has_more=has_more)


# Re-export for sibling compat modules
fetch_user_search = fetch_video_search
fetch_user_post_videos = fetch_video_search
