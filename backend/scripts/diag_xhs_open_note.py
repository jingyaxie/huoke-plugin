"""诊断 open_note_for_ui_action 各步骤。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUOKE_ROOT = ROOT.parent
if not os.environ.get("STORAGE_ROOT"):
    os.environ["STORAGE_ROOT"] = "storage/dev"
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{(HUOKE_ROOT / 'storage/dev/huoke.db').resolve()}"
sys.path.insert(0, str(ROOT))

NOTE_ID = "6a2a2fe4000000002003b077"
CONTENT_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_source=pc_search"


async def main() -> None:
    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.services.agent_browser_session import AgentBrowserSession
    from app.services.comment_reply_service import CommentReplyService
    from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
        detect_page_scene,
        open_note_for_ui_action,
        page_has_search_note_cards,
    )

    settings = get_settings()
    db = SessionLocal()
    svc = CommentReplyService(
        settings, tenant_id="default", platform="xiaohongshu", session=db
    )
    note_meta = svc._load_xhs_note_meta(NOTE_ID)
    print("note_meta:", json.dumps(
        {k: note_meta.get(k) for k in ("search_url", "xsec_token", "content_url")} if note_meta else {},
        ensure_ascii=False,
    ))

    browser = AgentBrowserSession("diag-open-note", "default", "xiaohongshu", settings, headless=False)
    page = await browser.ensure_started()
    print("start url:", page.url)

    result = await open_note_for_ui_action(
        page,
        settings,
        tenant_id="default",
        content_url=CONTENT_URL,
        note_id=NOTE_ID,
        note_meta=note_meta,
    )
    print("open_result:", json.dumps(result, ensure_ascii=False, indent=2))
    print("scene:", await detect_page_scene(page))
    print("has_cards:", await page_has_search_note_cards(page))
    print("final url:", page.url)

    db.close()
    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
