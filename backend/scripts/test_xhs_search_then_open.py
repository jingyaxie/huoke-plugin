#!/usr/bin/env python3
"""搜索后从列表点击打开笔记（验证缺 token 裸链时走 UI 点击）。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.platforms.xiaohongshu.comment_tool import XhsCommentTool
from app.platforms.xiaohongshu.search import XhsSearchTool
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.platforms.xiaohongshu.utils import build_note_url, extract_note_access_params, extract_note_id
from app.services.agent_browser_session import AgentBrowserSession
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import _page_note_access_ok


async def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "团餐"
    settings = get_settings()
    store = XhsSessionStore(settings)
    if not store.is_ready(store.load("default", "default")):
        print(json.dumps({"ok": False, "error": "登录态无效"}, ensure_ascii=False))
        return 1

    search = XhsSearchTool(settings, "default", store)
    comments = XhsCommentTool(settings, "default", store)
    browser = AgentBrowserSession(
        "test-xhs-search-open",
        "default",
        "xiaohongshu",
        settings,
        headless=os.environ.get("XHS_HEADLESS", "true").lower() in {"1", "true", "yes"},
    )
    report: dict = {"keyword": keyword, "ok": False}
    try:
        page = await browser.ensure_started()
        captured: list[str] = []
        note_urls, diagnostic = await search._ui_searchbar_keyword_search(
            page,
            keyword=keyword,
            limit=1,
            captured_api_urls=captured,
            days=7,
        )
        report["search_diagnostic"] = diagnostic
        report["note_urls"] = note_urls
        report["page_url_after_search"] = page.url
        if not note_urls:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        bare = note_urls[0]
        note_id = extract_note_id(bare)
        report["bare_url"] = bare
        report["bare_has_token"] = bool(extract_note_access_params(bare).get("xsec_token"))

        opened, warn = await comments._open_note_for_comments(page, note_id, bare)
        report["opened_url"] = opened
        report["opened_has_token"] = bool(extract_note_access_params(opened).get("xsec_token"))
        report["page_url"] = page.url
        report["page_ok"] = await _page_note_access_ok(page)
        report["warning"] = warn
        report["ok"] = bool(report["page_ok"])
    finally:
        await browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
