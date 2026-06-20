from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

from app.core.antibot import headless_for_platform, human_delay, require_login
from app.core.config import Settings
from app.platforms.douyin.js_constants import PLATFORM, _extract_aweme_id
from app.platforms.douyin.profile import AWEME_POST_PATH, DouyinProfileTool
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool
from app.services.ui_flow.platforms.douyin.search_parse import extract_aweme_items_from_json

_PROFILE_PATH_RE = re.compile(r"/user/([^/?#]+)")
_SEC_UID_RE = re.compile(r"^MS4w[\w-]+$", re.I)
_AWEME_ID_RE = re.compile(r"^\d{8,22}$")


def is_profile_post_api(url: str) -> bool:
    if not url or "douyin.com/aweme/v1/web/" not in url:
        return False
    return AWEME_POST_PATH.strip("/") in url or "/aweme/post/" in url


def is_douyin_short_url(url: str) -> bool:
    host = (urlparse(str(url or "").strip()).netloc or "").lower()
    return host == "v.douyin.com"


def resolve_douyin_short_url(url: str, *, timeout: float = 12.0) -> str | None:
    """解析 v.douyin.com 短链首跳 Location（不请求落地页）。"""
    raw = str(url or "").strip()
    if not is_douyin_short_url(raw):
        return None

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    req = urllib.request.Request(
        raw,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            location = str(exc.headers.get("Location") or "").strip()
            return location or None
    except Exception:
        return None
    return None


def parse_profile_input_url(url: str) -> dict[str, str]:
    """解析抖音主页/带 vid 的链接，返回 sec_uid、可选 vid、规范化 profile_url。"""
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("缺少 profile_url")

    if is_douyin_short_url(raw):
        resolved = resolve_douyin_short_url(raw)
        if resolved:
            try:
                return parse_profile_input_url(resolved)
            except ValueError:
                pass
        return {
            "sec_uid": "",
            "vid": "",
            "profile_url": raw,
            "input_kind": "short_link",
        }

    parsed = urlparse(raw)
    if "douyin.com" not in (parsed.netloc or ""):
        raise ValueError(f"非抖音链接: {raw}")

    video_match = re.search(r"/video/(\d{8,22})", parsed.path or "")
    if video_match:
        aweme_id = video_match.group(1)
        return {
            "sec_uid": "",
            "vid": aweme_id,
            "profile_url": f"https://www.douyin.com/video/{aweme_id}",
            "input_kind": "single_video",
        }

    path_match = _PROFILE_PATH_RE.search(parsed.path or "")
    if not path_match:
        raise ValueError(f"无法从链接解析用户主页: {raw}")
    sec_uid = path_match.group(1).strip()
    if not _SEC_UID_RE.match(sec_uid):
        raise ValueError(f"sec_uid 格式异常: {sec_uid}")

    query = parse_qs(parsed.query or "")
    vid = ""
    for key in ("vid", "modal_id"):
        vals = query.get(key) or []
        if vals and _AWEME_ID_RE.match(str(vals[0]).strip()):
            vid = str(vals[0]).strip()
            break

    profile_url = f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main"
    if vid:
        profile_url = f"{profile_url}&vid={vid}"

    return {
        "sec_uid": sec_uid,
        "vid": vid,
        "profile_url": profile_url,
        "input_kind": "profile",
    }


def _parse_create_time(row: dict) -> datetime | None:
    ts = row.get("create_time")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _publish_cutoff(days: int | None) -> datetime | None:
    if not days or days <= 0:
        return None
    # 与表单「1周内」一致：按自然日计算，包含 cutoff 当天 00:00 之后发布的视频。
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


def _newest_create_time(items: list[dict]) -> datetime | None:
    times = [_parse_create_time(row) for row in items]
    valid = [ts for ts in times if ts is not None]
    return max(valid) if valid else None


def _finalize_videos(
    api_items: dict[str, dict],
    *,
    limit: int,
    profile_url: str,
    sec_uid: str,
    capture_method: str,
    diagnostic: str | None = None,
    priority_vid: str = "",
) -> tuple[list[dict], str | None]:
    rows = list(api_items.values())
    if priority_vid and priority_vid in api_items:
        rows = [api_items[priority_vid], *[r for k, r in api_items.items() if k != priority_vid]]
    videos: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        aweme_id = str(row.get("aweme_id") or "")
        if not aweme_id or aweme_id in seen:
            continue
        seen.add(aweme_id)
        videos.append(
            {
                "aweme_id": aweme_id,
                "video_url": row.get("video_url") or f"https://www.douyin.com/video/{aweme_id}",
                "title": row.get("title") or "",
                "author": row.get("author") or "",
                "author_id": row.get("author_id") or "",
                "sec_uid": row.get("sec_uid") or sec_uid,
                "digg_count": row.get("digg_count"),
                "comment_count": row.get("comment_count"),
                "create_time": row.get("create_time"),
            }
        )
        if len(videos) >= limit:
            break
    diag = diagnostic
    if not videos and not diag:
        diag = f"主页未采集到视频；页 {profile_url}"
    return videos[:limit], diag


class DouyinProfileVideosTool(DouyinProfileTool):
    """打开抖音用户主页 URL，监听 aweme/post 接口采集视频列表（输出形态对齐搜索）。"""

    async def collect_videos_on_page(
        self,
        page,
        *,
        profile_url: str,
        limit: int = 10,
        days: int | None = None,
        captured_api_urls: list[str] | None = None,
    ) -> tuple[list[dict], str | None, str]:
        parsed = parse_profile_input_url(profile_url)
        if parsed.get("input_kind") == "single_video":
            aweme_id = parsed["vid"]
            return (
                [{"aweme_id": aweme_id, "video_url": parsed["profile_url"]}],
                "单视频链接，已直接作为视频源",
                "",
            )

        sec_uid = parsed["sec_uid"]
        open_url = parsed["profile_url"]
        priority_vid = parsed.get("vid") or ""
        api_items: dict[str, dict] = {}
        donors = captured_api_urls if captured_api_urls is not None else []

        async def on_response_async(resp) -> None:
            if not is_profile_post_api(resp.url) or resp.status >= 400:
                return
            try:
                data = await resp.json()
            except Exception:
                return
            donors.append(resp.url)
            for row in extract_aweme_items_from_json(data):
                api_items.setdefault(row["aweme_id"], row)

        page.on("response", on_response_async)
        try:
            await page.goto(open_url, wait_until="domcontentloaded", timeout=45000)
            try:
                await page.wait_for_selector('[data-e2e="user-detail"]', state="attached", timeout=15000)
            except Exception:
                pass
            cutoff = _publish_cutoff(days)
            max_scroll_rounds = 12 if cutoff else 8
            for _ in range(max_scroll_rounds):
                if len(api_items) >= limit and cutoff is None:
                    break
                filtered_preview = _filter_by_publish_days(list(api_items.values()), days)
                if cutoff is not None:
                    if len(filtered_preview) >= limit:
                        break
                    newest = _newest_create_time(list(api_items.values()))
                    if newest is not None and newest < cutoff:
                        break
                await human_delay(page, self.settings, tenant_id=self.tenant_id, profile="fast")
                try:
                    await page.mouse.wheel(0, 1200)
                except Exception:
                    pass
                await page.wait_for_timeout(800)
        finally:
            try:
                page.remove_listener("response", on_response_async)
            except Exception:
                pass

        filtered_rows = _filter_by_publish_days(list(api_items.values()), days)
        filtered_items = {row["aweme_id"]: row for row in filtered_rows if row.get("aweme_id")}

        diagnostic_extra = None
        if days and days > 0 and api_items and not filtered_rows:
            diagnostic_extra = f"主页近 {days} 天内未找到可抓取视频"

        videos, diagnostic = _finalize_videos(
            filtered_items,
            limit=limit,
            profile_url=open_url,
            sec_uid=sec_uid,
            capture_method="profile_url_api_listen",
            priority_vid=priority_vid,
            diagnostic=diagnostic_extra,
        )
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
            return await self.collect_videos_on_page(
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
            "sec_uid": parsed.get("sec_uid") or "",
            "priority_vid": parsed.get("vid") or "",
            "video_count": len(videos),
            "capture_method": capture_method,
            "diagnostic": diagnostic,
            "videos": videos,
        }
        safe = re.sub(r"[^\w-]+", "_", (parsed.get("sec_uid") or "profile"))[:24]
        output = (
            self.settings.report_output_dir
            / f"profile_videos_{PLATFORM}_{self.tenant_id}_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, output
