"""验证快手数据抓取：登录态、关键词搜索、单视频评论。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.platforms.kuaishou.comments import KuaishouCommentCrawler
from app.platforms.kuaishou.session import KuaishouSessionStore

KEYWORD = "美食"
SEARCH_LIMIT = 3
MAX_COMMENTS = 20


async def main() -> None:
    settings = get_settings()
    tenant_id = "default"
    account_id = "default"
    store = KuaishouSessionStore(settings)

    print("=" * 60)
    print("1. 登录态检查")
    status = store.login_status(tenant_id, account_id=account_id)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if not store.is_ready(store.load(tenant_id, account_id)):
        print("ERROR: 登录态无效，请先绑定快手账号")
        sys.exit(1)

    crawler = KuaishouCommentCrawler(settings, tenant_id, store, account_id=account_id)

    print("\n" + "=" * 60)
    print(f"2. 关键词搜索视频: {KEYWORD!r}, limit={SEARCH_LIMIT}")
    urls, diagnostic = await crawler.search_videos_by_keyword(
        KEYWORD, SEARCH_LIMIT, headless=True
    )
    print(f"  diagnostic: {diagnostic}")
    print(f"  found {len(urls)} videos:")
    for i, url in enumerate(urls, 1):
        print(f"    [{i}] {url}")

    if not urls:
        print("ERROR: 搜索未返回视频链接")
        sys.exit(2)

    print("\n" + "=" * 60)
    print(f"3. 抓取单视频评论 (max={MAX_COMMENTS})")
    video_url = urls[0]
    payload, output = await crawler.crawl_video_comments(
        video_url, show_browser=False, max_comments=MAX_COMMENTS
    )
    comments = payload.get("comments") or []
    print(f"  photo_id: {payload.get('photo_id')}")
    print(f"  photo_author_id: {payload.get('photo_author_id')}")
    print(f"  capture_method: {payload.get('capture_method')}")
    print(f"  api_total_top_comments: {payload.get('api_total_top_comments')}")
    print(f"  total_comments_captured: {payload.get('total_comments_captured')}")
    print(f"  warning: {payload.get('warning')}")
    print(f"  report: {output}")
    for i, c in enumerate(comments[:5], 1):
        user = c.get("username") or c.get("user_id") or "?"
        text = (c.get("comment") or "")[:80]
        print(f"    [{i}] @{user}: {text}")

    print("\n" + "=" * 60)
    print(f"4. 关键词评论组合抓取: {KEYWORD!r}, limit=2")
    results, files, kw_diag, session_meta = await crawler.crawl_keyword_comments(
        KEYWORD, limit=2, max_comments=10, show_browser=False, days=30
    )
    print(f"  diagnostic: {kw_diag}")
    print(f"  session_mode: {session_meta.get('session_mode')}")
    print(f"  videos crawled: {len(results)}")
    for row in results:
        print(
            f"    - {row.get('photo_id')}: "
            f"{row.get('total_comments_captured')} comments "
            f"({row.get('capture_method')})"
        )

    ok = bool(urls) and bool(comments)
    print("\n" + "=" * 60)
    print("RESULT:", "PASS" if ok else "PARTIAL/FAIL")
    if not ok:
        sys.exit(3)


if __name__ == "__main__":
    asyncio.run(main())
