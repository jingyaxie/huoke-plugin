from __future__ import annotations

import asyncio
import contextlib

from app.core.antibot import human_delay
from app.platforms.search_filters import SearchFilterOptions, fetch_multiplier
from app.platforms.xiaohongshu.search import XhsSearchTool
from app.platforms.xiaohongshu.ui_helpers import dismiss_login_overlay
from app.platforms.xiaohongshu.utils import extract_note_id
from app.services.ui_flow.platforms.xiaohongshu.filter_ui import (
    apply_ui_publish_time_filter,
    needs_ui_publish_filter,
)
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
    detect_page_scene,
    scroll_search_feed,
)
from app.services.ui_flow.platforms.xiaohongshu.ui_session import UiStepResult, XhsUiSession

CAPTURE_METHOD_PREFIX = "ui_flow_xiaohongshu_"


async def run_search(ctx: XhsUiSession) -> UiStepResult:
    keyword = str(ctx.params.keyword or "").strip()
    if not keyword:
        return UiStepResult(ok=False, error="E_KEYWORD", diagnostic="缺少 keyword")

    filters = SearchFilterOptions.from_params(
        keyword=keyword,
        region=ctx.params.region,
        days=ctx.params.days,
    )
    search_keyword = filters.composed_keyword()
    limit = max(int(ctx.params.content_limit or 3), 1)

    tool = XhsSearchTool(
        ctx.settings,
        ctx.tenant_id,
        account_id=ctx.account_id,
    )
    captured_api_urls: list[str] = []
    print(f"[search] keyword={search_keyword} url={ctx.page.url}", flush=True)

    note_meta: dict[str, dict] = {}
    target_count = max(limit * fetch_multiplier(filters), 10)
    processed: set[int] = set()
    pending: list[asyncio.Task] = []

    def on_response(resp) -> None:
        from app.platforms.xiaohongshu.js_constants import _is_search_result_api

        if not _is_search_result_api(resp.url):
            return
        pending.append(
            asyncio.create_task(
                tool._ingest_search_response(resp, note_meta, captured_api_urls, target_count, processed)
            )
        )

    ctx.page.on("response", on_response)
    try:
        if not await tool._ensure_feeds_top_search(ctx.page):
            return UiStepResult(ok=False, error="E_SEARCH_UI", diagnostic="探索页顶区搜索框未就绪")
        if not await tool._trigger_searchbar(ctx.page, search_keyword):
            return UiStepResult(
                ok=False,
                error="E_SEARCH_SUBMIT",
                diagnostic="未能通过搜索框完成搜索（禁止直接跳转搜索 URL）",
            )

        filter_label: str | None = None
        if needs_ui_publish_filter(ctx):
            print("[search] 应用 UI 筛选（发布时间）…", flush=True)
            filter_label = await apply_ui_publish_time_filter(ctx)
            print(f"[search] 筛选结果 filter={filter_label} steps={ctx.state.get('search_filter_steps')}", flush=True)
            note_meta.clear()
            processed.clear()

        note_urls, diagnostic = await tool._collect_search_results_on_page(
            ctx.page,
            limit=limit,
            filters=filters,
            captured_api_urls=captured_api_urls,
            pending=pending,
            note_meta=note_meta,
            processed=processed,
            region=ctx.params.region,
            days=ctx.params.days,
            search_keyword=search_keyword,
        )
    finally:
        await tool._drain_tasks(pending)
        with contextlib.suppress(Exception):
            ctx.page.remove_listener("response", on_response)

    if filter_label:
        suffix = f"；发布时间={filter_label}"
        if ctx.state.get("search_filter_verified") is False:
            steps = ctx.state.get("search_filter_steps") or []
            suffix += f"；筛选步骤={'>'.join(str(s) for s in steps)}"
        diagnostic = (diagnostic or "") + suffix
    if not note_urls:
        return UiStepResult(
            ok=False,
            error="E_SEARCH_EMPTY",
            diagnostic=diagnostic or f"关键词「{search_keyword}」未搜到笔记",
        )

    ctx.note_urls = list(note_urls)
    note_ids: list[str] = []
    for url in note_urls:
        try:
            note_ids.append(extract_note_id(url))
        except ValueError:
            note_ids.append("")
    ctx.state["search_note_ids"] = note_ids
    ctx.state["search_url"] = ctx.page.url
    ctx.state["captured_api_urls"] = captured_api_urls
    ctx.state["search_keyword"] = search_keyword
    ctx.state["search_ready"] = True

    with contextlib.suppress(Exception):
        await dismiss_login_overlay(ctx.page)
    await scroll_search_feed(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, rounds=2)
    await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="action")

    return UiStepResult(
        ok=True,
        diagnostic=diagnostic,
        data={
            "note_count": len(note_urls),
            "search_keyword": search_keyword,
            "page_scene": await detect_page_scene(ctx.page),
            "capture_method": f"{CAPTURE_METHOD_PREFIX}search",
        },
    )
