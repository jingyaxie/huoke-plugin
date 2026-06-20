#!/usr/bin/env python3
"""真实浏览器：小红书关键词搜评 + video_publish_days / comment_days 时间窗验证。"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.platforms.xiaohongshu.comments import XhsCommentCrawler
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.services.agent_browser_session import AgentBrowserSession


def _age_days(create_time: int | None) -> float | None:
    if not create_time:
        return None
    ts = int(create_time)
    if ts > 1_000_000_000_000:
        ts //= 1000
    return round((time.time() - ts) / 86400, 1)


async def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "团餐"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    video_publish_days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
    comment_days = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    timeout_s = int(sys.argv[5]) if len(sys.argv) > 5 else 300

    settings = get_settings()
    tenant_id = "default"
    account_id = "default"
    store = XhsSessionStore(settings)

    report: dict = {
        "keyword": keyword,
        "limit": limit,
        "video_publish_days": video_publish_days,
        "comment_days": comment_days,
        "storage_root": str(settings.storage_root),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    print("=" * 60)
    print("1. 登录态")
    status = store.login_status(tenant_id, account_id=account_id)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    report["login_status"] = status
    if not store.is_ready(store.load(tenant_id, account_id)):
        report["ok"] = False
        report["error"] = "登录态无效，请先在小红书绑定账号"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    crawler = XhsCommentCrawler(settings, tenant_id, store, account_id=account_id)
    browser = AgentBrowserSession(
        "test-xhs-time-limits",
        tenant_id,
        "xiaohongshu",
        settings,
        account_id=account_id,
        headless=os.environ.get("XHS_HEADLESS", "false").lower() in {"1", "true", "yes"},
    )

    t0 = time.time()
    try:
        page = await browser.ensure_started()
        await page.goto(
            settings.xhs_explore_url or settings.xhs_home_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(2000)

        print("\n" + "=" * 60)
        print(
            f"2. 关键词搜评 ui_search_only=True "
            f"publish={video_publish_days}d comment={comment_days}d limit={limit}"
        )

        results, files, diagnostic, session_meta = await asyncio.wait_for(
            crawler.crawl_keyword_comments(
                keyword,
                limit=limit,
                max_comments=80,
                days=video_publish_days,
                comment_days=comment_days,
                existing_page=page,
                ui_search_only=True,
            ),
            timeout=timeout_s,
        )

        items = []
        total_captured = 0
        for row in results:
            ctx = row.get("keyword_context") or {}
            comments = row.get("comments") or []
            ages = [_age_days(c.get("create_time")) for c in comments[:5]]
            ages = [a for a in ages if a is not None]
            total_captured += int(row.get("total_comments_captured") or len(comments))
            items.append(
                {
                    "note_url": row.get("note_url") or row.get("video_url"),
                    "capture_method": row.get("capture_method"),
                    "comment_days": row.get("comment_days"),
                    "warning": row.get("warning"),
                    "total_comments_captured": row.get("total_comments_captured"),
                    "api_total_top_comments": row.get("api_total_top_comments"),
                    "keyword_context": {
                        "video_publish_days": ctx.get("video_publish_days"),
                        "comment_days": ctx.get("comment_days"),
                        "days": ctx.get("days"),
                    },
                    "sample_comment_ages_days": ages,
                    "sample_texts": [
                        str(c.get("comment") or c.get("content") or "")[:40]
                        for c in comments[:3]
                    ],
                }
            )

        report.update(
            {
                "ok": bool(results) and total_captured >= 0,
                "elapsed_s": round(time.time() - t0, 1),
                "diagnostic": diagnostic,
                "session_meta": session_meta,
                "videos_processed": len(results),
                "total_comments_captured": total_captured,
                "items": items,
                "output_files": [str(p) for p in files],
            }
        )

        print(f"  diagnostic: {diagnostic}")
        print(f"  videos={len(results)} comments={total_captured}")
        for i, item in enumerate(items, 1):
            print(f"  [{i}] {item['note_url']}")
            print(f"      captured={item['total_comments_captured']} api_total={item['api_total_top_comments']}")
            print(f"      ctx={item['keyword_context']} ages={item['sample_comment_ages_days']}")
            if item.get("warning"):
                print(f"      warning: {item['warning']}")

    except asyncio.TimeoutError:
        report.update({"ok": False, "error": f"timeout_{timeout_s}s", "elapsed_s": round(time.time() - t0, 1)})
    except Exception as exc:
        report.update(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - t0, 1),
                "trace": traceback.format_exc()[-2000:],
            }
        )
    finally:
        with contextlib.suppress(Exception):
            await browser.close()

    print("\n" + "=" * 60)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
