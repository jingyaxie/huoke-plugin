#!/usr/bin/env python3
"""诊断精选页搜索框交互（有头，复用桌面 storage_state 登录态）。"""
from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEYWORD = sys.argv[1] if len(sys.argv) > 1 else "团餐"


async def main() -> int:
    from app.core.config import get_settings
    from app.platforms.douyin.session import DouyinSessionStore
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.search_ui import (
        _focus_search_input_via_dom,
        _read_search_input_value,
        _search_input_locator,
        run_searchbar_keyword_search,
    )
    from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession
    from app.services.playwright_pool import PlaywrightPool

    settings = get_settings()
    store = DouyinSessionStore(settings)
    login = store.login_status("default", account_id="default")
    pool = PlaywrightPool.get()
    report: dict = {
        "keyword": KEYWORD,
        "storage_root": str(settings.storage_root),
        "login_status": login,
        "steps": [],
    }

    if login.get("status") != "ready":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("登录态未就绪，请先在桌面 App 完成抖音账号绑定", file=sys.stderr)
        return 2

    async with pool.tenant_context(
        "douyin", "default", store, settings, headless=False, account_id="default"
    ) as (_, page):
        print("bootstrap ok", page.url, flush=True)
        loc = await _search_input_locator(page, settings, tenant_id="default")
        report["steps"].append(
            {
                "input_count": await loc.count(),
                "input_visible": await loc.is_visible() if await loc.count() else False,
                "placeholder": await loc.get_attribute("placeholder") if await loc.count() else None,
            }
        )
        focused = await _focus_search_input_via_dom(page)
        report["steps"].append({"dom_focus": focused})
        print("running search...", flush=True)
        result = await run_searchbar_keyword_search(
            page,
            settings,
            tenant_id="default",
            keyword=KEYWORD,
            limit=5,
        )
        params = parse_ui_flow_params(
            {"keyword": KEYWORD, "content_limit": 5, "ui_search_only": True},
            platform="douyin",
        )
        ctx = DouyinUiSession(
            settings=settings,
            tenant_id="default",
            account_id="default",
            params=params,
            page=page,
        )
        report["input_value"] = await _read_search_input_value(ctx)
        report["ok"] = result.ok
        report["error"] = result.error
        report["diagnostic"] = result.diagnostic
        report["page_url"] = page.url
        report["video_urls"] = list((result.data or {}).get("video_urls") or [])[:5]
        await asyncio.sleep(3)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
