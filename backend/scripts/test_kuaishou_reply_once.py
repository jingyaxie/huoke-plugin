#!/usr/bin/env python3
"""一键测试快手评论回复（需已登录；DB 有记录或手动传参）。"""
from __future__ import annotations

import asyncio
import json
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.comment_reply_service import CommentReplyService

# 默认用最近一次 crawl 报告里的评论；也可命令行传 comment_id video_url reply_text
DEFAULT_VIDEO_URL = "https://www.kuaishou.com/short-video/3x6jthbgnbjnfm4"
DEFAULT_COMMENT_ID = "1140757204980"
DEFAULT_REPLY_TEXT = "是啊，菜量真足，看着就很有食欲～"


async def main() -> int:
    comment_id = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_COMMENT_ID).strip()
    reply_text = (sys.argv[2] if len(sys.argv) > 2 else DEFAULT_REPLY_TEXT).strip()
    video_url = (sys.argv[3] if len(sys.argv) > 3 else DEFAULT_VIDEO_URL).strip()

    settings = get_settings()
    session = SessionLocal()
    try:
        service = CommentReplyService(
            settings,
            tenant_id="default",
            platform="kuaishou",
            session=session,
            account_id="default",
        )
        target = service.resolve_target(comment_id=comment_id, video_url=video_url)
        print("=== resolve_target ===", flush=True)
        if isinstance(target, dict):
            print(json.dumps(target, ensure_ascii=False, indent=2), flush=True)
            if target.get("status") == "failed" and video_url:
                target = service.resolve_target(comment_id=comment_id, video_url=video_url)
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
                    "photo_author_id": target.photo_author_id,
                    "reply_to_user_id": target.reply_to_user_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )

        result = await service.reply_comment(
            comment_id=comment_id,
            reply_text=reply_text,
            video_url=video_url,
            show_browser=False,
        )
        print("=== reply_result ===", flush=True)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0 if result.get("status") == "completed" else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
