from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, human_delay, human_scroll, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import COMMENT_PAGE_PATH, COMMENT_SUB_PATH, PLATFORM
from app.platforms.xiaohongshu.js_api import XhsJsApiTool
from app.platforms.xiaohongshu.js_constants import DEFAULT_MAX_COMMENTS, _build_comment_page_url
from app.platforms.xiaohongshu.utils import (
    extract_note_access_params,
    extract_note_id,
    normalize_xhs_comment,
    resolve_note_open_url,
)
from app.services.playwright_pool import PlaywrightPool


class XhsCommentTool(XhsJsApiTool):
    """小红书笔记评论抓取工具。"""

    async def crawl_note_comments(
        self,
        note_url: str,
        show_browser: bool = False,
        *,
        page=None,
        template_url: str | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> tuple[dict, Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        note_id = extract_note_id(note_url)
        payload = await self._fetch_note_comments(
            note_url=note_url,
            headless=not show_browser,
            page=page,
            template_url=template_url,
            max_comments=max_comments,
        )
        payload["platform"] = PLATFORM
        output = (
            self.settings.report_output_dir
            / f"comments_{self.platform}_{self.tenant_id}_{note_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output

    async def _fetch_note_comments(
        self,
        note_url: str,
        headless: bool = True,
        *,
        page=None,
        template_url: str | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict:
        note_id = extract_note_id(note_url)
        if page is not None:
            resolved_template = template_url or await self.pick_api_template_url(page)
            return await self._fetch_comments_via_nav(
                page,
                note_id,
                note_url,
                resolved_template,
                max_comments=max_comments,
            )

        pool = PlaywrightPool.get()
        resolved_headless = headless_for_platform(self.settings, PLATFORM, headless)
        captured_api_urls: list[str] = []

        async def on_response(resp):
            if COMMENT_PAGE_PATH in resp.url or COMMENT_SUB_PATH in resp.url:
                captured_api_urls.append(resp.url)

        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, session_page):
            session_page.on("response", on_response)
            try:
                await self.warmup_for_js_api(session_page, captured_api_urls)
                resolved_template = template_url or await self.pick_api_template_url(session_page, captured_api_urls)
                return await self._fetch_comments_via_nav(
                    session_page,
                    note_id,
                    note_url,
                    resolved_template,
                    max_comments=max_comments,
                )
            finally:
                try:
                    session_page.remove_listener("response", on_response)
                except Exception:
                    pass

    async def _open_note_for_comments(
        self,
        page,
        note_id: str,
        note_url: str,
    ) -> tuple[str, str | None]:
        """打开笔记详情；优先带 xsec_token 的链接，避免 explore/{id} 裸链 404。"""
        from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
            _click_note_on_search_list,
            _page_note_access_ok,
            find_note_href_on_search,
            page_has_search_note_cards,
        )

        access = extract_note_access_params(note_url)
        candidates: list[str] = []
        if note_url:
            candidates.append(note_url)
        resolved = resolve_note_open_url(note_id, content_url=note_url, note_meta={"note_id": note_id, **access})
        if resolved and resolved not in candidates:
            candidates.append(resolved)
        href = await find_note_href_on_search(page, note_id)
        if href and href not in candidates:
            candidates.insert(0, href)

        seen: set[str] = set()
        ordered: list[str] = []
        for url in candidates:
            key = str(url or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)

        warning: str | None = None

        on_search = "search_result" in (page.url or "") or await page_has_search_note_cards(page)
        if on_search and await _click_note_on_search_list(
            page,
            self.settings,
            tenant_id=self.tenant_id,
            note_id=note_id,
        ):
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            if await _page_note_access_ok(page):
                return str(page.url or note_url).strip(), None

        for open_url in ordered:
            if not extract_note_access_params(open_url).get("xsec_token"):
                continue
            await page.goto(open_url, wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            if await _page_note_access_ok(page):
                return open_url, None

        for open_url in ordered:
            await page.goto(open_url, wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="page_load")
            if await _page_note_access_ok(page):
                used = open_url
                if not extract_note_access_params(used).get("xsec_token"):
                    warning = "笔记链接缺少 xsec_token，页面可能不稳定或评论接口受限"
                return used, warning

        warning = "无法打开笔记详情（可能缺少 xsec_token 或笔记已删除）"
        fallback = ordered[0] if ordered else note_url
        return fallback, warning

    async def _fetch_comments_via_nav(
        self,
        page,
        note_id: str,
        note_url: str,
        template_url: str,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
    ) -> dict:
        access = extract_note_access_params(note_url)
        captured_pages: list[dict] = []
        open_warning: str | None = None

        async def on_response(resp):
            try:
                url = resp.url
                if COMMENT_PAGE_PATH not in url and COMMENT_SUB_PATH not in url:
                    return
                if resp.status != 200:
                    return
                data = await resp.json()
                if isinstance(data, dict):
                    captured_pages.append({"url": url, "data": data})
            except Exception:
                return

        page.on("response", on_response)
        try:
            note_url, open_warning = await self._open_note_for_comments(page, note_id, note_url)
            access = extract_note_access_params(note_url)
            from app.services.ui_flow.platforms.xiaohongshu.feed_ui import _page_note_access_ok

            if not await _page_note_access_ok(page):
                return {
                    "platform": PLATFORM,
                    "note_id": note_id,
                    "note_url": note_url,
                    "video_url": note_url,
                    "api_total_top_comments": 0,
                    "top_comments_captured": 0,
                    "total_comments_captured": 0,
                    "capture_method": "open_failed",
                    "warning": open_warning or "笔记详情打开失败（404 或缺少 xsec_token）",
                    "comments": [],
                }
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
        api_error: str | None = None
        for packet in captured_pages:
            body = packet.get("data") or {}
            if body.get("success") is False:
                api_error = str(body.get("msg") or body.get("code") or "comment_api_failed")
                continue
            data = body.get("data") if isinstance(body.get("data"), dict) else body
            comments = data.get("comments") or []
            if not api_total:
                api_total = int(data.get("comment_count") or data.get("total") or len(comments) or 0)
            for item in comments:
                row = normalize_xhs_comment(item)
                if row["comment_id"]:
                    comments_map[row["comment_id"]] = row
                for sub in item.get("sub_comments") or []:
                    sub_row = normalize_xhs_comment(sub, parent_comment_id=row["comment_id"])
                    if sub_row["comment_id"]:
                        comments_map[sub_row["comment_id"]] = sub_row

        if not comments_map:
            api_data = await self._fetch_comments_from_api(
                page,
                note_id,
                template_url,
                max_comments=max_comments,
                xsec_token=access.get("xsec_token"),
                xsec_source=access.get("xsec_source"),
            )
            if api_data.get("comments"):
                payload = {
                    "platform": PLATFORM,
                    "note_id": note_id,
                    "note_url": note_url,
                    "video_url": note_url,
                    **api_data,
                    "capture_method": api_data.get("capture_method") or "js_api",
                }
                if api_data.get("warning"):
                    payload["warning"] = api_data["warning"]
                return payload

            dom_rows = await self._extract_comments_from_dom(page)
            warning = "未捕获到小红书评论接口，结果来自页面可见评论（可能不全）。"
            if api_error:
                warning = f"{api_error}；{warning}"
            elif not access.get("xsec_token"):
                warning = "笔记链接缺少 xsec_token，评论接口可能拒绝访问；请通过搜索接口获取完整笔记链接。"
            if open_warning:
                warning = f"{open_warning}；{warning}" if warning else open_warning
            return {
                "platform": PLATFORM,
                "note_id": note_id,
                "note_url": note_url,
                "video_url": note_url,
                "api_total_top_comments": 0,
                "top_comments_captured": len(dom_rows),
                "reply_comments_captured_preview": 0,
                "expected_reply_total_from_top_comments": 0,
                "total_comments_captured": len(dom_rows),
                "capture_method": "dom_fallback",
                "warning": warning,
                "comments": dom_rows,
            }

        comments = list(comments_map.values())
        comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
        top_rows = [row for row in comments if not row.get("parent_comment_id")][:max_comments]
        kept_ids = {row["comment_id"] for row in top_rows}
        kept_ids.update(
            row["comment_id"]
            for row in comments
            if row.get("parent_comment_id") in kept_ids and row.get("comment_id")
        )
        comments = [row for row in comments if row.get("comment_id") in kept_ids]
        preview_reply_rows = [row for row in comments if row.get("parent_comment_id")]
        expected_reply_total = sum(int(row.get("reply_comment_total") or 0) for row in top_rows)
        warning = open_warning
        if api_total > max_comments:
            limit_note = f"已限制抓取前 {max_comments} 条顶层评论（接口总数 {api_total}）。"
            warning = f"{warning}；{limit_note}" if warning else limit_note
        return {
            "platform": PLATFORM,
            "note_id": note_id,
            "note_url": note_url,
            "video_url": note_url,
            "api_total_top_comments": api_total,
            "top_comments_captured": len(top_rows),
            "reply_comments_captured_preview": len(preview_reply_rows),
            "expected_reply_total_from_top_comments": expected_reply_total,
            "total_comments_captured": len(comments),
            "capture_method": "network_api",
            "warning": warning,
            "comments": comments,
        }

    async def _fetch_comments_from_api(
        self,
        page,
        note_id: str,
        template_url: str,
        *,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        xsec_token: str | None = None,
        xsec_source: str | None = None,
    ) -> dict:
        comments_map: dict[str, dict] = {}
        cursor = ""
        api_total = 0
        guard = 0
        top_count = 0

        def merge_page(data: dict) -> None:
            nonlocal top_count, api_total
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            comments = inner.get("comments") or []
            if not api_total:
                api_total = int(inner.get("comment_count") or inner.get("total") or len(comments) or 0)
            for item in comments:
                row = normalize_xhs_comment(item)
                if row["comment_id"]:
                    if row["comment_id"] not in comments_map and not row.get("parent_comment_id"):
                        top_count += 1
                    comments_map[row["comment_id"]] = row
                    for sub in item.get("sub_comments") or []:
                        sub_row = normalize_xhs_comment(sub, parent_comment_id=row["comment_id"])
                        if sub_row["comment_id"]:
                            comments_map[sub_row["comment_id"]] = sub_row

        has_more = True
        max_pages = max(20, (max_comments + 14) // 15)
        while has_more and guard < max_pages and top_count < max_comments:
            guard += 1
            url = _build_comment_page_url(
                template_url,
                note_id,
                cursor=cursor,
                xsec_token=xsec_token,
                xsec_source=xsec_source,
            )
            data = await self.fetch_json_via_page(page, url)
            if not data:
                break
            if data.get("success") is False:
                break
            merge_page(data)
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            cursor = str(inner.get("cursor") or "")
            has_more = bool(inner.get("has_more")) and bool(cursor)

        comments = list(comments_map.values())
        comments.sort(key=lambda x: x.get("create_time") or 0, reverse=True)
        top_rows = [row for row in comments if not row.get("parent_comment_id")][:max_comments]
        return {
            "platform": PLATFORM,
            "note_id": note_id,
            "api_total_top_comments": api_total,
            "top_comments_captured": len(top_rows),
            "total_comments_captured": len(comments),
            "capture_method": "js_api" if top_rows else "api_empty",
            "comments": comments,
        }

    async def _trigger_comment_panel(self, page) -> None:
        for selector in ('[class*="comment"]', 'span:has-text("评论")', 'div:has-text("条评论")'):
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
                const nodes = document.querySelectorAll('[class*="comment"], [class*="Comment"], .note-comment-item, li');
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
