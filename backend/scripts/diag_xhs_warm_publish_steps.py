#!/usr/bin/env python3
"""逐步诊断 warm_publish dry-run 失败点。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUOKE_ROOT = ROOT.parent
os.environ.setdefault("STORAGE_ROOT", str((HUOKE_ROOT / "storage/sidecar-dev").resolve()))
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite+pysqlite:///{(HUOKE_ROOT / 'storage/sidecar-dev/huoke_sidecar.db').resolve()}",
)
sys.path.insert(0, str(ROOT))

NOTE_URL = (
    "https://www.xiaohongshu.com/explore/68a2aa3b000000001d00eaaa"
    "?xsec_token=AB8ecVojqYkxXdqWlIpUvfQX7Lhwl7o4EHtAUvpCMPqHY%3D&xsec_source=pc_feed"
)
NOTE_ID = "68a2aa3b000000001d00eaaa"
COMMENT_ID = "69816b1500000000060085e8"
REPLY_TEXT = "同意"


async def main() -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.services.agent_browser_session import AgentBrowserSession
    from app.services.comment_reply_service import CommentReplyService
    from app.services.social_roam.human.xiaohongshu.reply_warm_publish import (
        _click_reply_on_visible_comment,
        _ensure_note_url_loaded,
        _pick_random_comment_item,
        _type_into_reply_input,
        _wait_comment_panel_ready,
        _wait_reply_popup,
        warm_publish_reply_comment,
    )
    from app.services.ui_flow.platforms.xiaohongshu.feed_ui import activate_comments_on_detail

    settings = get_settings()
    db = SessionLocal()
    browser = AgentBrowserSession("diag-warm-steps", "default", "xiaohongshu", settings, headless=False)
    page = await browser.ensure_started()
    svc = CommentReplyService(settings, tenant_id="default", platform="xiaohongshu", session=db)
    target = svc.resolve_target(comment_id=COMMENT_ID)
    note_meta = svc._load_xhs_note_meta(NOTE_ID)

    print("start_url:", page.url)
    await _ensure_note_url_loaded(page, content_url=target.content_url, note_id=NOTE_ID)
    print("after_goto:", page.url, "title:", await page.title())
    await activate_comments_on_detail(page, settings, tenant_id="default")

    panel = await _wait_comment_panel_ready(page, timeout_s=8.0)
    print("comment_panel:", panel, "items:", await page.locator(".comment-item").count())

    item = await _pick_random_comment_item(page)
    print("picked_item:", item is not None)

    clicked = await _click_reply_on_visible_comment(page, settings, tenant_id="default")
    print("click_reply_ok:", clicked)

    if clicked:
        typed = await _type_into_reply_input(
            page, settings, tenant_id="default", reply_text=REPLY_TEXT
        )
        print("typed_ok:", typed)

    print("\n=== full dry_run ===")
    await browser.close()
    browser2 = AgentBrowserSession("diag-warm-full", "default", "xiaohongshu", settings, headless=False)
    page2 = await browser2.ensure_started()
    result = await warm_publish_reply_comment(
        page2,
        settings,
        tenant_id="default",
        content_url=target.content_url,
        comment_id=COMMENT_ID,
        reply_text=REPLY_TEXT,
        note_id=NOTE_ID,
        note_meta=note_meta,
        dry_run=True,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    db.close()
    await browser2.close()


if __name__ == "__main__":
    asyncio.run(main())
