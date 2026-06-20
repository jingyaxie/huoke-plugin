#!/usr/bin/env python3
"""对比抖音多种搜索/抓取入口（复用桌面登录态）。"""
from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEYWORD = sys.argv[1] if len(sys.argv) > 1 else "淋浴房"
LIMIT = 3
METHOD_PAUSE_S = 20


async def _pause(label: str) -> None:
    print(f"[节奏] {label}，停顿 {METHOD_PAUSE_S}s …", flush=True)
    await asyncio.sleep(METHOD_PAUSE_S)


async def _method_ui_flow_search(page, settings) -> dict:
    from app.services.ui_flow.platforms.douyin.search_ui import run_searchbar_keyword_search

    result = await run_searchbar_keyword_search(
        page,
        settings,
        tenant_id="default",
        keyword=KEYWORD,
        limit=LIMIT,
    )
    return {
        "method": "run_searchbar_keyword_search",
        "ok": result.ok,
        "error": result.error,
        "diagnostic": result.diagnostic,
        "page_url": page.url,
        "video_count": len((result.data or {}).get("video_urls") or []),
    }


async def _method_keyword_search_tool(page, settings, store) -> dict:
    from app.platforms.douyin.search import DouyinSearchTool

    tool = DouyinSearchTool(settings, "default", store, account_id="default")
    captured: list[str] = []
    urls, diagnostic, _ = await tool.keyword_search(
        page,
        keyword=KEYWORD,
        limit=LIMIT,
        captured_api_urls=captured,
        headless=False,
        ui_search_only=True,
    )
    return {
        "method": "DouyinSearchTool.keyword_search(ui_search_only)",
        "ok": bool(urls),
        "diagnostic": diagnostic,
        "page_url": page.url,
        "video_count": len(urls),
        "video_urls_preview": urls[:3],
        "api_captured": len(captured),
    }


async def _method_human_type_enter(page, settings) -> dict:
    from app.core.antibot import human_click, human_delay, human_type
    from app.services.ui_flow.platforms.douyin.search_ui import (
        _ensure_searchbar_ready,
        _jingxuan_search_url,
        _on_search_results_page,
        _search_input_locator,
    )
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession
    from app.services.ui_flow.params import parse_ui_flow_params

    params = parse_ui_flow_params({"keyword": KEYWORD, "ui_search_only": True}, platform="douyin")
    ctx = DouyinUiSession(
        settings=settings,
        tenant_id="default",
        account_id="default",
        params=params,
        page=page,
    )
    if not await _ensure_searchbar_ready(ctx):
        return {"method": "human_type+Enter", "ok": False, "error": "searchbar_not_ready"}
    inp = await _search_input_locator(page, settings, tenant_id="default")
    if not await inp.count():
        return {"method": "human_type+Enter", "ok": False, "error": "no_search_input"}
    await human_click(page, inp, settings, tenant_id="default")
    await human_type(page, inp, KEYWORD, settings, tenant_id="default")
    await asyncio.sleep(0.3)
    await page.keyboard.press("Enter")
    for _ in range(12):
        if _on_search_results_page(page.url) or "/jingxuan/search/" in (page.url or ""):
            break
        await asyncio.sleep(0.4)
    links = await page.locator('a[href*="/video/"]').count()
    return {
        "method": "human_type+Enter",
        "ok": links > 0 or _on_search_results_page(page.url) or "/jingxuan/search/" in (page.url or ""),
        "page_url": page.url,
        "video_links": links,
        "fallback_url": _jingxuan_search_url(KEYWORD),
    }


async def _method_prepare_only(page, settings) -> dict:
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.prepare_ui import run_prepare
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

    params = parse_ui_flow_params({"keyword": KEYWORD, "ui_search_only": True}, platform="douyin")
    ctx = DouyinUiSession(
        settings=settings,
        tenant_id="default",
        account_id="default",
        params=params,
        page=page,
    )
    result = await run_prepare(ctx)
    return {
        "method": "run_prepare",
        "ok": result.ok,
        "error": result.error,
        "diagnostic": result.diagnostic,
        "page_url": page.url,
    }


async def main() -> int:
    from app.core.config import get_settings
    from app.platforms.douyin.session import DouyinSessionStore
    from app.services.playwright_pool import PlaywrightPool

    settings = get_settings()
    store = DouyinSessionStore(settings)
    login = store.login_status("default", account_id="default")
    report: dict = {
        "keyword": KEYWORD,
        "storage_root": str(settings.storage_root),
        "login_status": login.get("status"),
        "user_logged_in": login.get("user_logged_in"),
        "methods": [],
    }
    if login.get("status") != "ready":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    pool = PlaywrightPool.get()

    async with pool.tenant_window(
        "douyin", "default", store, settings, headless=False, account_id="default"
    ) as win:
        tab = await win.open_tab(reuse_main=True)
        report["methods"].append(await _method_prepare_only(tab, settings))
        await _pause("prepare done")
        await win.close_tab(tab)

        tab = await win.open_tab()
        report["methods"].append(await _method_human_type_enter(tab, settings))
        await _pause("human_type done")
        await win.close_tab(tab)

        tab = await win.open_tab()
        report["methods"].append(await _method_ui_flow_search(tab, settings))
        await _pause("ui_flow done")
        await win.close_tab(tab)

        tab = await win.open_tab()
        report["methods"].append(await _method_keyword_search_tool(tab, settings, store))
        await win.close_tab(tab)

    ok_count = sum(1 for m in report["methods"] if m.get("ok"))
    report["summary"] = f"{ok_count}/{len(report['methods'])} methods ok"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok_count == len(report["methods"]) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
