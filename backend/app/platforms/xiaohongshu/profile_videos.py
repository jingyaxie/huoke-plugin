from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.antibot import headless_for_platform, human_delay, require_login
from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_constants import PLATFORM
from app.platforms.xiaohongshu.profile import USER_POSTED_PATH, XhsProfileTool, build_profile_url
from app.platforms.xiaohongshu.utils import (
    build_note_url,
    extract_note_access_params,
    extract_note_id,
    parse_note_card,
)
from app.services.playwright_pool import PlaywrightPool

_PROFILE_PATH_RE = re.compile(r"/user/profile/([0-9a-fA-F]{16,32})")
_NOTE_PATH_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-fA-F]{16,32})")


def is_user_posted_api(url: str) -> bool:
    if not url or "xiaohongshu.com" not in url:
        return False
    return USER_POSTED_PATH.strip("/") in url or "/user_posted" in url


def parse_profile_input_url(url: str) -> dict[str, str]:
    """解析小红书主页 / 笔记入口链接。"""
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("缺少 profile_url")
    parsed = urlparse(raw)
    if "xiaohongshu.com" not in (parsed.netloc or ""):
        raise ValueError(f"非小红书链接: {raw}")

    note_match = _NOTE_PATH_RE.search(parsed.path or "")
    if note_match:
        note_id = note_match.group(1)
        access = extract_note_access_params(raw)
        return {
            "user_id": "",
            "note_id": note_id,
            "note_url": raw.split("#", 1)[0],
            "profile_url": "",
            "input_kind": "note_entry",
            "xsec_token": access.get("xsec_token") or "",
            "xsec_source": access.get("xsec_source") or "pc_feed",
        }

    profile_match = _PROFILE_PATH_RE.search(parsed.path or "")
    if not profile_match:
        raise ValueError(f"无法从链接解析用户主页或笔记: {raw}")
    user_id = profile_match.group(1)
    return {
        "user_id": user_id,
        "note_id": "",
        "note_url": "",
        "profile_url": build_profile_url(user_id),
        "input_kind": "profile",
        "xsec_token": "",
        "xsec_source": "",
    }


def _parse_create_time(row: dict) -> datetime | None:
    ts = row.get("create_time")
    if ts is None:
        return None
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return None
    if value > 10_000_000_000:
        value //= 1000
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _publish_cutoff(days: int | None) -> datetime | None:
    if not days or days <= 0:
        return None
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start - timedelta(days=int(days))


def _filter_by_publish_days(items: list[dict], days: int | None) -> list[dict]:
    cutoff = _publish_cutoff(days)
    if cutoff is None:
        return items
    filtered: list[dict] = []
    for row in items:
        created = _parse_create_time(row)
        if created is None:
            continue
        if created >= cutoff:
            filtered.append(row)
    return filtered


def _ingest_user_posted_payload(data: dict, *, user_id: str, rank_start: int) -> list[dict]:
    body = data.get("data") if isinstance(data.get("data"), (dict, list)) else data
    note_list = body.get("notes") if isinstance(body, dict) else body
    if isinstance(note_list, dict):
        note_list = note_list.get("notes") or note_list.get("items") or []
    if not isinstance(note_list, list):
        return []

    rows: list[dict] = []
    rank = rank_start
    for item in note_list:
        if not isinstance(item, dict):
            continue
        parsed = parse_note_card(item, rank=rank, tenant_id="")
        if parsed:
            rank += 1
            note_id = parsed.get("external_id") or ""
            raw = parsed.get("raw_data") if isinstance(parsed.get("raw_data"), dict) else {}
            rows.append(
                {
                    "note_id": note_id,
                    "video_url": parsed.get("video_url") or build_note_url(note_id),
                    "title": parsed.get("title") or "",
                    "author_id": raw.get("author_id") or user_id,
                    "author_name": parsed.get("author_name") or "",
                    "create_time": parsed.get("create_time"),
                    "comment_count": parsed.get("comment_count"),
                    "like_count": parsed.get("like_count"),
                    "xsec_token": raw.get("xsec_token"),
                    "xsec_source": raw.get("xsec_source"),
                }
            )
            continue
        note_card = item.get("note_card") or item
        note_id = str(note_card.get("note_id") or note_card.get("id") or item.get("id") or "").strip()
        if not note_id:
            continue
        user = note_card.get("user") or note_card.get("author") or {}
        interact = note_card.get("interact_info") or {}
        token = note_card.get("xsec_token") or item.get("xsec_token")
        source = note_card.get("xsec_source") or item.get("xsec_source") or "pc_feed"
        rows.append(
            {
                "note_id": note_id,
                "video_url": build_note_url(note_id, token, source),
                "title": (note_card.get("display_title") or note_card.get("title") or "")[:500],
                "author_id": user.get("user_id") or user.get("userId") or user_id,
                "author_name": user.get("nickname") or user.get("nick_name") or "",
                "create_time": note_card.get("time") or item.get("time"),
                "comment_count": interact.get("comment_count"),
                "like_count": interact.get("liked_count"),
                "xsec_token": token,
                "xsec_source": source,
            }
        )
    return rows


def _finalize_notes(
    api_items: dict[str, dict],
    *,
    limit: int,
    profile_url: str,
    user_id: str,
    capture_method: str,
    diagnostic: str | None = None,
    priority_note_id: str = "",
) -> tuple[list[dict], str | None]:
    rows = list(api_items.values())
    if priority_note_id and priority_note_id in api_items:
        rows = [api_items[priority_note_id], *[r for k, r in api_items.items() if k != priority_note_id]]
    videos: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        note_id = str(row.get("note_id") or "")
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        videos.append(row)
        if len(videos) >= limit:
            break
    diag = diagnostic
    if not videos and not diag:
        diag = f"主页未采集到笔记；页 {profile_url}"
    return videos[:limit], diag


class XhsProfileVideosTool(XhsProfileTool):
    """打开小红书用户主页，监听 user_posted 接口采集笔记列表（输出形态对齐抖音 profile_videos）。"""

    async def _resolve_author_from_note(
        self,
        page,
        *,
        note_url: str,
        note_id: str,
    ) -> tuple[str, str, str | None]:
        await page.goto(note_url, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(1500)
        resolved = await page.evaluate(
            """() => {
                const pick = (href) => {
                    const m = (href || '').match(/\\/user\\/profile\\/([0-9a-fA-F]{16,32})/);
                    return m ? m[1] : '';
                };
                for (const a of document.querySelectorAll('a[href*="/user/profile/"]')) {
                    const uid = pick(a.href || a.getAttribute('href') || '');
                    if (uid) return { user_id: uid, nickname: (a.textContent || '').trim().slice(0, 40) };
                }
                try {
                    const state = window.__INITIAL_STATE__ || {};
                    const detailMap = state.note && state.note.noteDetailMap;
                    if (detailMap && typeof detailMap === 'object') {
                        for (const val of Object.values(detailMap)) {
                            const user = (val && val.note && val.note.user) || (val && val.user) || {};
                            const uid = user.userId || user.user_id || '';
                            if (uid) return { user_id: String(uid), nickname: user.nickname || user.nickName || '' };
                        }
                    }
                } catch (e) {}
                return null;
            }"""
        )
        user_id = str((resolved or {}).get("user_id") or "").strip()
        nickname = str((resolved or {}).get("nickname") or "").strip() or None
        if user_id:
            return user_id, build_profile_url(user_id), nickname
        raise ValueError(f"无法从笔记 {note_id} 解析博主 user_id，请直接使用主页链接")

    async def collect_notes_on_page(
        self,
        page,
        *,
        profile_url: str,
        limit: int = 10,
        days: int | None = None,
        captured_api_urls: list[str] | None = None,
    ) -> tuple[list[dict], str | None, str]:
        parsed = parse_profile_input_url(profile_url)
        priority_note_id = parsed.get("note_id") or ""
        user_id = parsed.get("user_id") or ""
        open_url = parsed.get("profile_url") or profile_url
        diagnostic_note: str | None = None

        if parsed.get("input_kind") == "note_entry":
            user_id, open_url, nickname = await self._resolve_author_from_note(
                page,
                note_url=parsed.get("note_url") or profile_url,
                note_id=priority_note_id,
            )
            diagnostic_note = f"由笔记入口解析博主 {nickname or user_id}"

        api_items: dict[str, dict] = {}
        donors = captured_api_urls if captured_api_urls is not None else []

        async def on_response_async(resp) -> None:
            if not is_user_posted_api(resp.url) or resp.status >= 400:
                return
            try:
                data = await resp.json()
            except Exception:
                return
            donors.append(resp.url)
            for row in _ingest_user_posted_payload(data, user_id=user_id, rank_start=len(api_items) + 1):
                api_items.setdefault(row["note_id"], row)

        page.on("response", on_response_async)
        try:
            await page.goto(open_url, wait_until="domcontentloaded", timeout=120000)
            await page.wait_for_timeout(1500)
            cutoff = _publish_cutoff(days)
            max_scroll_rounds = 12 if cutoff else 8
            for _ in range(max_scroll_rounds):
                if len(api_items) >= limit and cutoff is None:
                    break
                filtered_preview = _filter_by_publish_days(list(api_items.values()), days)
                if cutoff is not None and len(filtered_preview) >= limit:
                    break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="fast")
                try:
                    await page.mouse.wheel(0, 1200)
                except Exception:
                    pass
                await page.wait_for_timeout(800)

            if len(api_items) < limit:
                template_url = await self.pick_api_template_url(page, donors)
                if template_url and user_id:
                    fetch_limit = max(limit, 15)
                    if cutoff is not None:
                        fetch_limit = max(fetch_limit, limit * 3)
                    cursor = ""
                    guard = 0
                    while guard < 8 and len(api_items) < fetch_limit:
                        guard += 1
                        data = await self.fetch_self_notes(
                            page,
                            template_url,
                            user_id,
                            limit=fetch_limit,
                        )
                        rows = _ingest_user_posted_payload(data, user_id=user_id, rank_start=len(api_items) + 1)
                        if not rows:
                            break
                        for row in rows:
                            api_items.setdefault(row["note_id"], row)
                        inner = data.get("data") if isinstance(data.get("data"), dict) else data
                        cursor = str(inner.get("cursor") or "")
                        if not cursor or not inner.get("has_more"):
                            break
        finally:
            try:
                page.remove_listener("response", on_response_async)
            except Exception:
                pass

        filtered_rows = _filter_by_publish_days(list(api_items.values()), days)
        filtered_items = {row["note_id"]: row for row in filtered_rows if row.get("note_id")}
        diagnostic_extra = None
        if days and days > 0 and api_items and not filtered_rows:
            diagnostic_extra = f"主页近 {days} 天内未找到可抓取笔记"

        videos, diagnostic = _finalize_notes(
            filtered_items,
            limit=limit,
            profile_url=open_url,
            user_id=user_id,
            capture_method="profile_url_api_listen",
            priority_note_id=priority_note_id,
            diagnostic=diagnostic_extra,
        )
        if diagnostic_note:
            diagnostic = f"{diagnostic_note}；{diagnostic}" if diagnostic else diagnostic_note
        capture = "profile_url_api_listen" if videos else "profile_url_empty"
        return videos, diagnostic, capture

    async def collect_profile_videos(
        self,
        profile_url: str,
        limit: int = 10,
        show_browser: bool = False,
        days: int | None = None,
        *,
        existing_page=None,
    ) -> tuple[dict[str, Any], Path]:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        parsed = parse_profile_input_url(profile_url)
        headless = headless_for_platform(self.settings, PLATFORM, not show_browser)
        captured: list[str] = []

        async def _run(page) -> tuple[list[dict], str | None, str]:
            return await self.collect_notes_on_page(
                page,
                profile_url=profile_url,
                limit=limit,
                days=days,
                captured_api_urls=captured,
            )

        if existing_page is not None and not existing_page.is_closed():
            videos, diagnostic, capture_method = await _run(existing_page)
        else:
            pool = PlaywrightPool.get()
            async with pool.tenant_context(
                PLATFORM,
                self.tenant_id,
                self.store,
                self.settings,
                headless=headless,
                account_id=self.account_id,
            ) as (_, page):
                videos, diagnostic, capture_method = await _run(page)

        payload = {
            "platform": PLATFORM,
            "profile_url": parsed.get("profile_url") or profile_url,
            "user_id": parsed.get("user_id") or (videos[0].get("author_id") if videos else ""),
            "priority_note_id": parsed.get("note_id") or "",
            "video_count": len(videos),
            "note_count": len(videos),
            "capture_method": capture_method,
            "diagnostic": diagnostic,
            "videos": videos,
            "notes": videos,
        }
        safe = re.sub(r"[^\w-]+", "_", (payload.get("user_id") or "profile"))[:24]
        output = (
            self.settings.report_output_dir
            / f"profile_videos_{PLATFORM}_{self.tenant_id}_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
