#!/usr/bin/env python3
"""真实浏览器：验证单条笔记链接（含/不含 xsec_token）能否正常打开。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.platforms.xiaohongshu.comment_tool import XhsCommentTool
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.platforms.xiaohongshu.utils import build_note_url, extract_note_access_params, extract_note_id
from app.services.agent_browser_session import AgentBrowserSession
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import _page_note_access_ok


DEFAULT_FULL = (
    "https://www.xiaohongshu.com/explore/6a1e6114000000002003b64f"
    "?xsec_token=ABk6U0Y3MsNhMO4R5OlBOQV2J2ijfRBIfE5EDVvrSX8cQ="
    "&xsec_source=pc_search&source=web_explore_feed"
)


async def _probe(page, tool: XhsCommentTool, label: str, note_url: str) -> dict:
    note_id = extract_note_id(note_url)
    t0 = time.time()
    opened_url, warn = await tool._open_note_for_comments(page, note_id, note_url)
    ok = await _page_note_access_ok(page)
    return {
        "label": label,
        "input_url": note_url,
        "opened_url": opened_url,
        "has_xsec_token": bool(extract_note_access_params(opened_url).get("xsec_token")),
        "page_url": page.url,
        "page_ok": ok,
        "warning": warn,
        "elapsed_s": round(time.time() - t0, 1),
    }


async def main() -> int:
    full_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FULL
    note_id = extract_note_id(full_url)
    bare_url = build_note_url(note_id, None, "pc_search")

    settings = get_settings()
    store = XhsSessionStore(settings)
    if not store.is_ready(store.load("default", "default")):
        print(json.dumps({"ok": False, "error": "登录态无效"}, ensure_ascii=False))
        return 1

    tool = XhsCommentTool(settings, "default", store)
    browser = AgentBrowserSession(
        "test-xhs-note-open",
        "default",
        "xiaohongshu",
        settings,
        headless=os.environ.get("XHS_HEADLESS", "false").lower() in {"1", "true", "yes"},
    )
    report: dict = {"storage_root": str(settings.storage_root), "cases": []}
    try:
        page = await browser.ensure_started()
        report["cases"].append(await _probe(page, tool, "full_url_with_token", full_url))
        report["cases"].append(await _probe(page, tool, "bare_url_no_token", bare_url))
        report["ok"] = all(c.get("page_ok") for c in report["cases"] if c["label"] == "full_url_with_token")
    finally:
        await browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
