#!/usr/bin/env python3
"""自动测试：首页预热 + JS 搜索 + JS 评论。"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback

from app.core.config import get_settings
from app.platforms.douyin.comments import DouyinCommentCrawler
from app.platforms.douyin.session import DouyinSessionStore


async def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "护肤"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    timeout_s = int(sys.argv[3]) if len(sys.argv) > 3 else 120

    settings = get_settings()
    crawler = DouyinCommentCrawler(settings, "default", DouyinSessionStore(settings))
    report: dict = {"keyword": keyword, "limit": limit, "timeout_s": timeout_s}

    t0 = time.time()
    try:
        guest_mode = "--guest" in sys.argv
        results, files, diagnostic, session_meta = await asyncio.wait_for(
            crawler.crawl_keyword_comments(
                keyword, limit=limit, max_comments=30, guest_mode=guest_mode
            ),
            timeout=timeout_s,
        )
        report.update(
            {
                "ok": bool(results),
                "elapsed_s": round(time.time() - t0, 1),
                "diagnostic": diagnostic,
                "guest_mode": session_meta.get("guest_mode"),
                "session_mode": session_meta.get("session_mode"),
                "videos_found": len(results),
                "items": [
                    {
                        "aweme_id": row.get("aweme_id"),
                        "capture_method": row.get("capture_method"),
                        "total_comments_captured": row.get("total_comments_captured"),
                        "sample_comment": (row.get("comments") or [{}])[0].get("comment", "")[:40],
                    }
                    for row in results
                ],
                "output_files": [str(path) for path in files],
            }
        )
    except asyncio.TimeoutError:
        report.update({"ok": False, "error": f"timeout_{timeout_s}s", "elapsed_s": round(time.time() - t0, 1)})
    except Exception as exc:
        report.update(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - t0, 1),
                "trace": traceback.format_exc()[-1000:],
            }
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
