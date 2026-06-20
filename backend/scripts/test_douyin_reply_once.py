#!/usr/bin/env python3
"""一键测试抖音评论回复（需已登录 + DB 中有评论记录）。"""
from __future__ import annotations

import asyncio
import json
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.repositories.content_comment_repository import ContentCommentRepository
from app.services.comment_reply_service import CommentReplyService

# 默认取 DB 中最新视频的第一条顶层评论；也可通过环境变量或命令行覆盖
DEFAULT_REPLY_TEXT = "感谢关注，有问题可以私信我哦"


async def _pick_target(session) -> tuple[str, str] | None:
    repo = ContentCommentRepository(session, "default")
    summaries, _ = repo.list_content_summaries(platform="douyin", limit=1)
    if not summaries:
        return None
    content_id = summaries[0].content_id
    for row in repo.list_by_content(platform="douyin", content_id=content_id):
        if not row.parent_comment_id and row.comment_id:
            return row.comment_id, row.comment_text or ""
    return None


async def main() -> int:
    comment_id = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    reply_text = (sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REPLY_TEXT).strip()

    settings = get_settings()
    session = SessionLocal()
    try:
        if not comment_id:
            picked = await _pick_target(session)
            if not picked:
                print("DB 中无抖音评论，请先抓取评论入库", flush=True)
                return 1
            comment_id, hint = picked
            print(f"自动选取 comment_id={comment_id} text={hint[:40]!r}", flush=True)

        service = CommentReplyService(
            settings,
            tenant_id="default",
            platform="douyin",
            session=session,
            account_id="default",
        )
        target = service.resolve_target(comment_id=comment_id)
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
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )

        result = await service.reply_comment(
            comment_id=comment_id,
            reply_text=reply_text,
            show_browser=False,
        )
        print("=== reply_result ===", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result.get("status") == "completed" else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
