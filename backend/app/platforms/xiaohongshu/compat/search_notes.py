from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.compat.envelope import CompatError
from app.services.compat.normalizers import notes_to_xhs_list
from app.services.compat.runtime import execute_skill

XHS_SEARCH_TIMEOUT_S = 120
XHS_COMMENTS_TIMEOUT_S = 90


async def search_notes(
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
    limit = int(body.get("page_size") or body.get("count") or body.get("limit") or 10)
    limit = max(1, min(limit, 20))
    try:
        result = await asyncio.wait_for(
            execute_skill(
                settings,
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                platform="xiaohongshu",
                skill_id="search-content",
                params={"keyword": keyword, "limit": limit, "show_browser": False},
            ),
            timeout=XHS_SEARCH_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        raise CompatError(f"小红书搜索超时（{XHS_SEARCH_TIMEOUT_S}s），请稍后重试", code=504)
    if result.get("error"):
        raise CompatError(str(result.get("error")), code=502)
    inner = result.get("result") or result
    notes = inner.get("notes") or inner.get("videos") or inner.get("videos_preview") or []
    if not notes:
        raise CompatError(inner.get("diagnostic") or "未搜索到笔记", code=404)
    return notes_to_xhs_list(notes)


async def get_note_detail(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    note_id = str(body.get("note_id") or body.get("id") or "").strip()
    note_url = str(body.get("note_url") or body.get("url") or "").strip()
    if not note_url and note_id:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if not note_url:
        raise CompatError("缺少 note_id 或 note_url", code=400)
    result = await execute_skill(
        settings,
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        platform="xiaohongshu",
        skill_id="content-comments",
        params={"note_url": note_url, "show_browser": False, "max_comments": 1},
    )
    if result.get("error"):
        raise CompatError(str(result.get("error")), code=502)
    inner = result.get("result") or result
    return {
        "items": [
            {
                "id": note_id or inner.get("note_id") or "",
                "note_id": note_id or inner.get("note_id") or "",
                "note_url": note_url,
                "title": inner.get("title") or "",
            }
        ]
    }


async def get_note_comments(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    from app.services.compat.normalizers import comments_to_tikhub_xhs

    note_id = str(body.get("note_id") or body.get("id") or "").strip()
    note_url = str(body.get("note_url") or body.get("url") or "").strip()
    if not note_url and note_id:
        note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if not note_url:
        raise CompatError("缺少 note_id 或 note_url", code=400)
    max_comments = int(body.get("num") or body.get("count") or 200)
    try:
        result = await asyncio.wait_for(
            execute_skill(
                settings,
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                platform="xiaohongshu",
                skill_id="content-comments",
                params={"note_url": note_url, "max_comments": max_comments, "show_browser": False},
            ),
            timeout=XHS_COMMENTS_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        raise CompatError(f"小红书评论抓取超时（{XHS_COMMENTS_TIMEOUT_S}s）", code=504)
    if result.get("error"):
        raise CompatError(str(result.get("error")), code=502)
    inner = result.get("result") or result
    comments = inner.get("comments") or inner.get("comments_preview") or []
    return comments_to_tikhub_xhs(comments)


async def get_note_sub_comments(*args, **kwargs) -> dict[str, Any]:
    return await get_note_comments(*args, **kwargs)


async def search_users(*args, **kwargs) -> dict[str, Any]:
    return {"users": [], "has_more": False}


async def get_user_info(*args, **kwargs) -> dict[str, Any]:
    return {"user": {}}


async def get_user_posted_notes(*args, **kwargs) -> dict[str, Any]:
    return {"notes": [], "has_more": False}
