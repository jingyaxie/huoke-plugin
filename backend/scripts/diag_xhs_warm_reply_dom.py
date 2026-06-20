#!/usr/bin/env python3
"""诊断 warm_publish 评论区 DOM。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUOKE_ROOT = ROOT.parent
if not os.environ.get("STORAGE_ROOT"):
    os.environ["STORAGE_ROOT"] = str((HUOKE_ROOT / "storage/sidecar-dev").resolve())
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        f"sqlite+pysqlite:///{(HUOKE_ROOT / 'storage/sidecar-dev/huoke_sidecar.db').resolve()}"
    )
sys.path.insert(0, str(ROOT))

NOTE_URL = (
    "https://www.xiaohongshu.com/explore/68a2aa3b000000001d00eaaa"
    "?xsec_token=AB8ecVojqYkxXdqWlIpUvfQX7Lhwl7o4EHtAUvpCMPqHY%3D&xsec_source=pc_feed"
)
NOTE_ID = "68a2aa3b000000001d00eaaa"


async def main() -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.services.agent_browser_session import AgentBrowserSession
    from app.services.comment_reply_service import CommentReplyService
    from app.services.social_roam.human.xiaohongshu.reply_warm_publish import (
        _COMMENT_ITEM_SELECTORS,
        _ITEM_REPLY_BTN_SELECTORS,
        _click_reply_on_visible_comment,
        _ensure_on_note_page,
        _wait_comment_panel_ready,
    )
    from app.services.ui_flow.platforms.xiaohongshu.note_ui import trigger_comment_panel

    settings = get_settings()
    db = SessionLocal()
    browser = AgentBrowserSession("diag-warm-reply", "default", "xiaohongshu", settings, headless=False)
    page = await browser.ensure_started()
    svc = CommentReplyService(settings, tenant_id="default", platform="xiaohongshu", session=db)
    note_meta = svc._load_xhs_note_meta(NOTE_ID)

    try:
        stage = await _ensure_on_note_page(
            page, settings, tenant_id="default", content_url=NOTE_URL, note_id=NOTE_ID, note_meta=note_meta
        )
    except Exception as exc:
        print("ensure_on_note_page failed:", exc)
        await page.goto(NOTE_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(3)
        stage = "goto_fallback"
    print("stage:", stage, "url:", page.url, "title:", await page.title())

    panel = await trigger_comment_panel(page, settings, tenant_id="default")
    ready = await _wait_comment_panel_ready(page)
    print("panel:", panel, "ready:", ready)

    counts = {}
    for sel in _COMMENT_ITEM_SELECTORS:
        try:
            counts[sel] = await page.locator(sel).count()
        except Exception as exc:
            counts[sel] = str(exc)
    print("comment_item_counts:", json.dumps(counts, ensure_ascii=False))

    diag = await page.evaluate(
        """() => {
          const parents = [...document.querySelectorAll('.parent-comment')].slice(0, 3);
          const samples = parents.map((item) => {
            const replyCandidates = [...item.querySelectorAll('*')].filter((el) => {
              const t = (el.textContent || '').trim();
              return t === '回复' || t.endsWith('回复');
            }).slice(0, 5).map((el) => ({
              tag: el.tagName,
              class: el.className,
              text: (el.textContent || '').trim().slice(0, 20),
              childCount: el.children.length,
            }));
            const replyClass = [...item.querySelectorAll('[class*="reply"]')].slice(0, 5).map((el) => ({
              tag: el.tagName,
              class: el.className,
              text: (el.textContent || '').trim().slice(0, 20),
            }));
            return { replyCandidates, replyClass, html: item.innerHTML.slice(0, 500) };
          });
          return { samples, parentCount: document.querySelectorAll('.parent-comment').length };
        }"""
    )
    print("reply_diag:", json.dumps(diag, ensure_ascii=False, indent=2)[:4000])

    ok = await _click_reply_on_visible_comment(page, settings, tenant_id="default")
    print("click_reply_ok:", ok)

    db.close()
    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
