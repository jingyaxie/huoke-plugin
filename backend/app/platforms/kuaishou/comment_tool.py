from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, human_delay, human_scroll, require_login
from app.core.config import Settings
from app.platforms.kuaishou.constants import GRAPHQL_PATH, PLATFORM
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.js_constants import (
    COMMENT_LIST_OPERATION,
    COMMENT_LIST_QUERY,
    DEFAULT_MAX_COMMENTS,
    VIDEO_DETAIL_OPERATION,
    VIDEO_DETAIL_QUERY,
    _is_comment_graphql_request,
)
from app.platforms.kuaishou.utils import (
    extract_photo_author_from_page,
    extract_photo_id,
    normalize_ks_comment,
    parse_video_detail,
    resolve_photo_author_id,
)
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool


class KuaishouCommentTool(KuaishouJsApiTool):
    """快手视频评论抓取工具。"""

    async def crawl_video_comments(
        self,
        video_url: str,
        show_browser: bool = False,
        *,
        page=None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        photo_id = extract_photo_id(video_url)
        payload = await self._fetch_video_comments(
            video_url=video_url,
            headless=not show_browser,
            page=page,
            max_comments=max_comments,
        )
        payload["platform"] = PLATFORM
        output = (
            self.settings.report_output_dir
            / f"comments_{self.platform}_{self.tenant_id}_{photo_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output

    async def crawl_note_comments(self, content_url: str, show_browser: bool = False, **kwargs) -> tuple[dict, Path]:
        return await self.crawl_video_comments(content_url, show_browser=show_browser, **kwargs)

    async def _fetch_video_comments(
        self,
        video_url: str,
        headless: bool = True,
        *,
        page=None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict:
        photo_id = extract_photo_id(video_url)
        if page is not None:
            return await self._fetch_comments_via_nav(page, photo_id, video_url, max_comments=max_comments)

        pool = PlaywrightPool.get()
        resolved_headless = headless_for_platform(self.settings, PLATFORM, headless)
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, session_page):
            await self.warmup_for_js_api(session_page, [])
            return await self._fetch_comments_via_nav(
                session_page,
                photo_id,
                video_url,
                max_comments=max_comments,
            )

    async def _fetch_comments_via_nav(
        self,
        page,
        photo_id: str,
        video_url: str,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict:
        captured_pages: list[dict] = []

        async def on_response(resp):
            try:
                if GRAPHQL_PATH not in resp.url:
                    return
                post = resp.request.post_data or ""
                if not _is_comment_graphql_request(post):
                    return
                data = await resp.json()
                if isinstance(data, dict):
                    captured_pages.append({"data": data})
            except Exception:
                return

        page.on("response", on_response)
        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=120000)
            for _ in range(6):
                if captured_pages:
                    break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
                await human_scroll(page, self.settings, tenant_id=self.tenant_id)
                await self._trigger_comment_panel(page)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        comments_map: dict[str, dict] = {}
        api_total = 0
        for packet in captured_pages:
            vision = (packet.get("data") or {}).get("data", {}).get("visionCommentList") or {}
            if not api_total:
                api_total = int(vision.get("commentCountV2") or vision.get("commentCount") or 0)
            for item in vision.get("rootCommentsV2") or []:
                row = normalize_ks_comment(item)
                if row["comment_id"]:
                    comments_map[row["comment_id"]] = row

        page_author_id = await extract_photo_author_from_page(page)

        if not comments_map:
            api_data = await self._fetch_comments_from_graphql(page, photo_id, max_comments=max_comments)
            if api_data.get("comments"):
                api_data["video_url"] = video_url
                if page_author_id:
                    api_data["photo_author_id"] = page_author_id
                return api_data
            dom_rows = await self._extract_comments_from_dom(page)
            return {
                "platform": PLATFORM,
                "photo_id": photo_id,
                "photo_author_id": page_author_id,
                "author_id": page_author_id,
                "video_url": video_url,
                "api_total_top_comments": 0,
                "top_comments_captured": len(dom_rows),
                "reply_comments_captured_preview": 0,
                "expected_reply_total_from_top_comments": 0,
                "total_comments_captured": len(dom_rows),
                "capture_method": "dom_fallback",
                "warning": "未捕获到快手评论接口，结果来自页面可见评论（可能不全）。",
                "comments": dom_rows,
            }

        comments = list(comments_map.values())
        comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
        top_rows = comments[:max_comments]
        detail = await self.graphql_via_page(
            page,
            operation_name=VIDEO_DETAIL_OPERATION,
            query=VIDEO_DETAIL_QUERY,
            variables={"photoId": photo_id},
        )
        video_detail = parse_video_detail(detail)
        photo_author_id = video_detail.get("photo_author_id") or resolve_photo_author_id(detail, photo_id) or page_author_id
        warning = None
        if api_total > max_comments:
            warning = f"已限制抓取前 {max_comments} 条顶层评论（接口总数 {api_total}）。"
        return {
            "platform": PLATFORM,
            "photo_id": photo_id,
            "photo_author_id": photo_author_id,
            "author_id": photo_author_id,
            "video_url": video_url,
            "api_total_top_comments": api_total,
            "top_comments_captured": len(top_rows),
            "reply_comments_captured_preview": 0,
            "expected_reply_total_from_top_comments": 0,
            "total_comments_captured": len(top_rows),
            "capture_method": "graphql_api",
            "warning": warning,
            "comments": top_rows,
        }

    async def _fetch_comments_from_graphql(
        self,
        page,
        photo_id: str,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict:
        comments_map: dict[str, dict] = {}
        pcursor = ""
        api_total = 0
        guard = 0
        while guard < 15 and len(comments_map) < max_comments:
            guard += 1
            data = await self.graphql_via_page(
                page,
                operation_name=COMMENT_LIST_OPERATION,
                query=COMMENT_LIST_QUERY,
                variables={"photoId": photo_id, "pcursor": pcursor},
            )
            vision = (data.get("data") or {}).get("visionCommentList") or {}
            if not api_total:
                api_total = int(vision.get("commentCountV2") or vision.get("commentCount") or 0)
            rows = vision.get("rootCommentsV2") or []
            if not rows:
                break
            for item in rows:
                row = normalize_ks_comment(item)
                if row["comment_id"]:
                    comments_map[row["comment_id"]] = row
            pcursor = str(vision.get("pcursor") or "")
            if not pcursor:
                break

        comments = list(comments_map.values())[:max_comments]
        return {
            "platform": PLATFORM,
            "photo_id": photo_id,
            "api_total_top_comments": api_total,
            "top_comments_captured": len(comments),
            "total_comments_captured": len(comments),
            "capture_method": "js_graphql" if comments else "graphql_empty",
            "comments": comments,
        }

    async def _trigger_comment_panel(self, page) -> None:
        for selector in ('span:has-text("评论")', 'div:has-text("条评论")', '[class*="comment"]'):
            loc = page.locator(selector).first
            try:
                if await loc.count() > 0:
                    await loc.click(force=True, timeout=800)
                    await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="action")
            except Exception:
                continue

    async def _extract_comments_from_dom(self, page) -> list[dict]:
        rows = await page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                const nodes = document.querySelectorAll('[class*="comment"], [class*="Comment"], li');
                for (const el of nodes) {
                    const textEl = el.querySelector('[class*="content"], [class*="text"], p, span');
                    const userEl = el.querySelector('[class*="name"], [class*="nickname"], a');
                    const comment = textEl ? (textEl.textContent || '').trim() : (el.textContent || '').trim();
                    const username = userEl ? (userEl.textContent || '').trim() : '';
                    if (!comment || comment.length < 2 || !username) continue;
                    const key = username + '::' + comment;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({
                        comment_id: '',
                        parent_comment_id: null,
                        comment,
                        create_time: null,
                        digg_count: 0,
                        reply_comment_total: 0,
                        username,
                        user_id: '',
                        sec_uid: '',
                        avatar: '',
                    });
                    if (out.length >= 200) break;
                }
                return out;
            }"""
        )
        return rows if isinstance(rows, list) else []
