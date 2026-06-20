#!/usr/bin/env python3
"""测试小红书 warm_publish：定位目标评论 → 点回复 → 原生 comment/post。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUOKE_ROOT = ROOT.parent
SIDECAR_ENV = HUOKE_ROOT / ".env.sidecar"

if not os.environ.get("STORAGE_ROOT"):
    os.environ["STORAGE_ROOT"] = str((HUOKE_ROOT / "storage/sidecar-dev").resolve())
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        f"sqlite+pysqlite:///{(HUOKE_ROOT / 'storage/sidecar-dev/huoke_sidecar.db').resolve()}"
    )
sys.path.insert(0, str(ROOT))

DEFAULT_COMMENT_ID = "69816b1500000000060085e8"
DEFAULT_REPLY_TEXT = "同意"


async def main() -> int:
    parser = argparse.ArgumentParser(description="测试小红书 warm_publish 回复")
    parser.add_argument("--comment-id", default=DEFAULT_COMMENT_ID)
    parser.add_argument("--reply-text", default=DEFAULT_REPLY_TEXT)
    parser.add_argument("--dry-run", action="store_true", help="只暖场+输入，不点发送")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.db.session import SessionLocal
    from app.services.agent_browser_session import AgentBrowserSession
    from app.services.comment_reply_service import CommentReplyService

    settings = get_settings()
    db = SessionLocal()
    browser = AgentBrowserSession(
        "test-xhs-warm-publish",
        "default",
        "xiaohongshu",
        settings,
        headless=args.headless,
    )
    try:
        page = await browser.ensure_started()
        service = CommentReplyService(
            settings,
            tenant_id="default",
            platform="xiaohongshu",
            session=db,
            account_id="default",
        )
        target = service.resolve_target(comment_id=args.comment_id)
        print("=== resolve_target ===", flush=True)
        if isinstance(target, dict):
            print(json.dumps(target, ensure_ascii=False, indent=2), flush=True)
            return 1
        print(
            json.dumps(
                {
                    "comment_id": target.comment_id,
                    "content_id": target.content_id,
                    "content_url": target.content_url,
                    "comment_text": target.comment_text,
                    "nickname": target.nickname,
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )

        result = await service.reply_comment(
            comment_id=target.comment_id,
            reply_text=args.reply_text,
            content_url=target.content_url,
            page=page,
            warm_publish=True,
            dry_run=args.dry_run,
            show_browser=not args.headless,
        )
        print("=== warm_publish_result ===", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result.get("status") == "completed" else 2
    finally:
        db.close()
        await browser.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
