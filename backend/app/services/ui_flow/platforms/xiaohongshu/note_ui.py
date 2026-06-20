from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.platforms.xiaohongshu.constants import COMMENT_PAGE_PATH, COMMENT_SUB_PATH
from app.platforms.xiaohongshu.utils import normalize_xhs_comment
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
    activate_comments_on_detail,
    scroll_comment_list_in_detail,
    scroll_search_feed,
)


async def trigger_comment_panel(page, settings: Settings, *, tenant_id: str) -> bool:
    return await activate_comments_on_detail(page, settings, tenant_id=tenant_id)


async def scroll_note_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 3,
) -> None:
    await scroll_comment_list_in_detail(
        page, settings, tenant_id=tenant_id, rounds=max(1, rounds)
    )


async def scroll_comment_area(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 4,
) -> None:
    await scroll_comment_list_in_detail(
        page, settings, tenant_id=tenant_id, rounds=max(1, rounds)
    )


async def scroll_search_results_feed(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 2,
) -> None:
    await scroll_search_feed(page, settings, tenant_id=tenant_id, rounds=max(1, rounds))


def merge_comment_api_pages(
    captured_pages: list[dict[str, Any]],
    *,
    max_comments: int,
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    comments_map: dict[str, dict[str, Any]] = {}
    api_total = 0
    for packet in captured_pages:
        body = packet.get("data") or {}
        if body.get("success") is False:
            continue
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        comments = data.get("comments") or []
        if not api_total:
            api_total = int(data.get("comment_count") or data.get("total") or len(comments) or 0)
        for item in comments:
            row = normalize_xhs_comment(item)
            if row.get("comment_id"):
                comments_map[row["comment_id"]] = row
            for sub in item.get("sub_comments") or []:
                sub_row = normalize_xhs_comment(sub, parent_comment_id=row.get("comment_id"))
                if sub_row.get("comment_id"):
                    comments_map[sub_row["comment_id"]] = sub_row

    comments = list(comments_map.values())
    comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
    top_rows = [row for row in comments if not row.get("parent_comment_id")][:max_comments]
    return comments, api_total, top_rows


def is_comment_api_url(url: str) -> bool:
    return COMMENT_PAGE_PATH in url or COMMENT_SUB_PATH in url
