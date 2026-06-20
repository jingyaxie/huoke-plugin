from __future__ import annotations

import contextlib

from app.platforms.xiaohongshu.search import XhsSearchTool
from app.platforms.xiaohongshu.ui_helpers import dismiss_login_overlay
from app.services.ui_flow.platforms.xiaohongshu.ui_session import UiStepResult, XhsUiSession


def _on_xhs_site(url: str) -> bool:
    return "xiaohongshu.com" in (url or "")


async def run_prepare(ctx: XhsUiSession) -> UiStepResult:
    """探索页就绪：顶栏常驻搜索框在布局上存在即可（非弹层）。"""
    tool = XhsSearchTool(ctx.settings, ctx.tenant_id)
    entry_url = tool.entry_url()
    try:
        if not _on_xhs_site(ctx.page.url):
            await ctx.page.goto(entry_url, wait_until="domcontentloaded", timeout=60000)
        await ctx.page.wait_for_timeout(1500)
        with contextlib.suppress(Exception):
            await dismiss_login_overlay(ctx.page)
        if not await tool._ensure_feeds_top_search(ctx.page):
            raise RuntimeError("探索页顶区搜索框未加载（#search-input-in-feeds）")
    except Exception as exc:
        return UiStepResult(ok=False, error="E_PAGE_NOT_READY", diagnostic=str(exc))

    ctx.state["prepare_done"] = True
    with contextlib.suppress(Exception):
        await ctx.page.bring_to_front()
    return UiStepResult(ok=True, data={"entry_url": entry_url, "page_url": ctx.page.url})
