from __future__ import annotations

import random

from app.core.antibot import human_delay
from app.platforms.xiaohongshu.utils import extract_note_id
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
    click_search_note_at_index,
    detect_page_scene,
    scroll_comment_list_in_detail,
)
from app.services.ui_flow.platforms.xiaohongshu.search_ui import CAPTURE_METHOD_PREFIX
from app.services.ui_flow.platforms.xiaohongshu.ui_session import UiStepResult, XhsUiSession


async def _resolve_note_url_at_index(ctx: XhsUiSession, index: int) -> str:
    if index < len(ctx.note_urls):
        return str(ctx.note_urls[index] or "").strip()
    return ""


async def _resolve_note_id_at_index(ctx: XhsUiSession, index: int) -> str:
    stored = ctx.state.get("search_note_ids")
    if isinstance(stored, list) and len(stored) > index:
        return str(stored[index] or "").strip()
    url = await _resolve_note_url_at_index(ctx, index)
    if url:
        try:
            return extract_note_id(url)
        except ValueError:
            return ""
    return ""


async def run_browse(ctx: XhsUiSession) -> UiStepResult | None:
    if not ctx.state.get("search_ready"):
        return None
    content_limit = int(ctx.params.content_limit or 0)
    if content_limit > 0 and ctx.browse_index >= content_limit:
        return None

    index = ctx.browse_index
    note_url = await _resolve_note_url_at_index(ctx, index)
    note_id = await _resolve_note_id_at_index(ctx, index)
    if not note_url and not note_id:
        return None

    ctx.phase_log.append(f"BROWSE click search note index={index} note_id={note_id or '?'}")

    try:
        open_result = await click_search_note_at_index(
            ctx,
            index,
            note_id=note_id,
            fallback_url=note_url,
        )
    except Exception as exc:
        ctx.browse_index += 1
        return UiStepResult(ok=False, error="E_BROWSE", diagnostic=str(exc))

    if not open_result.get("ok"):
        ctx.browse_index += 1
        return UiStepResult(
            ok=False,
            error="E_BROWSE",
            diagnostic=f"未点开第 {index + 1} 个搜索笔记（method={open_result.get('method')}）",
        )

    lo = max(3, ctx.params.watch_seconds_min)
    hi = max(lo, ctx.params.watch_seconds_max)
    watch_sec = random.randint(lo, hi)
    await ctx.page.wait_for_timeout(watch_sec * 1000)

    comments_ok = await scroll_comment_list_in_detail(
        ctx.page,
        ctx.settings,
        tenant_id=ctx.tenant_id,
        rounds=2,
    )
    ctx.phase_log.append(
        f"BROWSE scene={await detect_page_scene(ctx.page)} comments_scroll={comments_ok}"
    )

    resolved_url = note_url or ctx.page.url or ""
    open_href = str(open_result.get("note_href") or "").strip()
    if open_href and note_id in open_href:
        resolved_url = open_href
    elif note_id and note_id in (ctx.page.url or ""):
        resolved_url = ctx.page.url
    elif note_id and note_id not in resolved_url:
        from app.platforms.xiaohongshu.utils import resolve_note_open_url

        resolved_url = resolve_note_open_url(note_id, content_url=note_url or ctx.page.url)

    ctx.state["last_browse_url"] = resolved_url
    ctx.state["last_note_id"] = note_id
    ctx.state["feed_mode"] = True
    ctx.browse_index += 1

    return UiStepResult(
        ok=True,
        data={
            "note_url": resolved_url,
            "note_id": note_id,
            "index": index,
            "detail_open": open_result.get("detail_open"),
            "open_method": open_result.get("method"),
            "comments_ok": comments_ok,
            "capture_method": f"{CAPTURE_METHOD_PREFIX}search_feed_note",
        },
    )
