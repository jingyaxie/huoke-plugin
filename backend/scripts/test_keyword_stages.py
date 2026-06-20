#!/usr/bin/env python3
"""分阶段测试：首页 JS API 搜索 → 搜索框兜底 → JS 评论。"""
from __future__ import annotations

import asyncio
import json
import sys
import time

from app.core.config import get_settings
from app.platforms.douyin.comments import DouyinCommentCrawler
from app.platforms.douyin.session import DouyinSessionStore
from app.services.playwright_pool import PlaywrightPool


async def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "护肤"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    settings = get_settings()
    crawler = DouyinCommentCrawler(settings, "default", DouyinSessionStore(settings))
    report: dict = {"keyword": keyword, "limit": limit, "mode": "js_api_then_ui"}
    t0 = time.time()

    pool = PlaywrightPool.get()
    try:
        async with pool.tenant_context(
            "douyin", "default", crawler.store, settings, headless=False, account_id="default"
        ) as (_, page):
            captured: list[str] = []

            def on_response(resp) -> None:
                if "/aweme/v1/web/" in resp.url:
                    captured.append(resp.url)

            page.on("response", on_response)

            s = time.time()
            urls, diagnostic, template = await crawler._search.keyword_search(
                page,
                keyword=keyword,
                limit=limit,
                captured_api_urls=captured,
                headless=False,
                manual_search=False,
            )
            report["search"] = {
                "elapsed_s": round(time.time() - s, 2),
                "diagnostic": diagnostic,
                "videos": urls,
                "template": template[:120],
                "captured_apis": len(captured),
                "page_url": page.url,
            }

            if urls:
                s = time.time()
                aweme_id = urls[0].split("/video/")[-1]
                comments = await crawler._fetch_comments_from_api(
                    page, aweme_id, urls[0], template, max_comments=10,
                )
                report["comments"] = {
                    "elapsed_s": round(time.time() - s, 2),
                    "aweme_id": aweme_id,
                    "method": comments.get("capture_method"),
                    "count": comments.get("total_comments_captured"),
                }
                report["ok"] = True
            else:
                report["ok"] = False

            page.remove_listener("response", on_response)
    except Exception as exc:
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"

    report["total_elapsed_s"] = round(time.time() - t0, 2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
