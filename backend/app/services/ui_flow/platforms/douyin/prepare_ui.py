from __future__ import annotations

import asyncio
import contextlib

from app.platforms.douyin.human_guards import HumanBrowseGuardError, is_captcha_page
from app.services.ui_flow.platforms.douyin.search_ui import _search_input_locator
from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession, UiStepResult

_SEARCH_INPUT = '[data-e2e="searchbar-input"]'
_WAIT_SEARCHBAR_ROUNDS = 20
_WAIT_SEARCHBAR_INTERVAL_SEC = 0.25


def resolve_entry_url(settings, entry: str) -> str:
    if entry == "hot":
        return settings.douyin_hot_url
    return settings.douyin_home_url


async def _searchbar_visible(page, settings=None, tenant_id: str = "default") -> bool:
    try:
        from app.services.ui_flow.platforms.douyin.search_ui import _search_input_locator

        loc = await _search_input_locator(page, settings, tenant_id=tenant_id)
        return await loc.count() > 0 and await loc.is_visible()
    except Exception:
        return False


def _on_douyin_site(url: str) -> bool:
    return "douyin.com" in (url or "")


async def _wait_searchbar(page, settings=None, tenant_id: str = "default") -> bool:
    for _ in range(_WAIT_SEARCHBAR_ROUNDS):
        if await _searchbar_visible(page, settings, tenant_id=tenant_id):
            return True
        await asyncio.sleep(_WAIT_SEARCHBAR_INTERVAL_SEC)
    return False


_JINGXUAN_HOME = "https://www.douyin.com/jingxuan"


async def run_prepare(ctx: DouyinUiSession) -> UiStepResult:
    """轻量首页就绪：搜索框可见即过。"""
    if ctx.params.ui_search_only:
        entry_url = _JINGXUAN_HOME
    else:
        entry_url = resolve_entry_url(ctx.settings, ctx.params.entry)
    try:
        if ctx.params.ui_search_only and "/search/" in (ctx.page.url or ""):
            if ctx.state.get("reuse_search_session"):
                from app.services.ui_flow.platforms.douyin.search_ui import page_ready_for_search_reuse

                if await page_ready_for_search_reuse(ctx):
                    ctx.state["prepare_done"] = True
                    with contextlib.suppress(Exception):
                        await ctx.page.bring_to_front()
                    return UiStepResult(
                        ok=True,
                        data={
                            "entry_url": ctx.page.url,
                            "page_url": ctx.page.url,
                            "reused_search": True,
                        },
                    )
            await ctx.page.goto(entry_url, wait_until="domcontentloaded", timeout=45000)
        elif not await _searchbar_visible(ctx.page, ctx.settings, tenant_id=ctx.tenant_id):
            if _on_douyin_site(ctx.page.url):
                if not await _wait_searchbar(ctx.page, ctx.settings, tenant_id=ctx.tenant_id):
                    await ctx.page.goto(entry_url, wait_until="domcontentloaded", timeout=45000)
            else:
                await ctx.page.goto(entry_url, wait_until="domcontentloaded", timeout=45000)
        if await is_captcha_page(ctx.page):
            return UiStepResult(ok=False, error="E_CAPTCHA", diagnostic="验证码中间页")
        if not await _searchbar_visible(ctx.page, ctx.settings, tenant_id=ctx.tenant_id):
            if not await _wait_searchbar(ctx.page, ctx.settings, tenant_id=ctx.tenant_id):
                raise HumanBrowseGuardError("搜索框未出现")
    except HumanBrowseGuardError as exc:
        return UiStepResult(ok=False, error="E_PAGE_NOT_READY", diagnostic=str(exc))

    ctx.state["prepare_done"] = True
    if ctx.params.ui_search_only:
        with contextlib.suppress(Exception):
            await ctx.page.bring_to_front()
        search_input = await _search_input_locator(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
        with contextlib.suppress(Exception):
            await search_input.scroll_into_view_if_needed()
    return UiStepResult(ok=True, data={"entry_url": entry_url, "page_url": ctx.page.url})
