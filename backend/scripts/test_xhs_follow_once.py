#!/usr/bin/env python3
"""测试小红书 warm_outreach 关注：入库评论者 user_id → 直达主页 → 关注。"""
from __future__ import annotations

import argparse
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

DEFAULT_COMMENT_ID = "69816b1500000000060085e8"


async def main() -> int:
    parser = argparse.ArgumentParser(description="测试小红书 warm_outreach 关注")
    parser.add_argument("--comment-id", default=DEFAULT_COMMENT_ID)
    parser.add_argument("--dry-run", action="store_true", help="暖场进主页，不点关注")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.repositories.content_comment_repository import ContentCommentRepository
    from app.services.agent_browser_session import AgentBrowserSession
    from app.services.skill_executor import SkillExecutor
    from app.services.playwright_tools import PlaywrightToolExecutor
    from app.services.supervisor_outreach import _user_ids_from_comment_row

    settings = get_settings()
    db = SessionLocal()
    browser = AgentBrowserSession(
        "test-xhs-follow",
        "default",
        "xiaohongshu",
        settings,
        headless=args.headless,
    )
    try:
        page = await browser.ensure_started()
        record = ContentCommentRepository(db, "default").find_comment_record(
            platform="xiaohongshu",
            comment_id=args.comment_id,
        )
        if record is None:
            print(json.dumps({"error": f"评论不存在: {args.comment_id}"}, ensure_ascii=False))
            return 1

        user_id, sec_uid = _user_ids_from_comment_row(
            {"user_id": "", "sec_uid": "", "raw_data": record.raw_data}
        )
        print(
            "=== target ===",
            json.dumps(
                {
                    "comment_id": record.comment_id,
                    "content_id": record.content_id,
                    "content_url": record.content_url,
                    "comment_text": record.comment_text,
                    "nickname": record.nickname,
                    "user_id": user_id,
                    "sec_uid": sec_uid,
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        if not user_id:
            print(json.dumps({"error": "评论 raw_data 缺少 user_id"}, ensure_ascii=False))
            return 1

        executor = SkillExecutor(
            settings,
            "default",
            "xiaohongshu",
            browser,
            PlaywrightToolExecutor(browser, settings),
            db_session=db,
        )
        executor._record_interaction_log = lambda *a, **k: None  # noqa: SLF001

        result = await executor._execute_follow(
            {
                "comment_id": record.comment_id,
                "comment_text": record.comment_text,
                "content_url": record.content_url,
                "user_id": user_id,
                "nickname": record.nickname,
                "warm_outreach": True,
                "dry_run": args.dry_run,
                "show_browser": not args.headless,
            },
            action="follow",
        )
        print("=== follow_result ===", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result.get("status") == "completed" else 2
    finally:
        db.close()
        await browser.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
