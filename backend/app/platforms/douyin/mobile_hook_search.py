"""抖音 Hook 搜索适配：Bridge 响应 → huoke 视频 schema。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.platforms.douyin.mobile_hook_client import DouyinMobileHookClient

logger = logging.getLogger(__name__)
PLATFORM = "douyin"
CAPTURE_METHOD = "mobile_hook_bridge"


def build_hook_client(settings: Settings) -> DouyinMobileHookClient:
    return DouyinMobileHookClient(
        host=settings.douyin_mobile_hook_host,
        port=settings.douyin_mobile_hook_port,
        timeout=settings.douyin_mobile_hook_timeout_seconds,
        token=settings.douyin_mobile_hook_token,
        adb_serial=settings.douyin_mobile_hook_adb_serial,
        auto_forward=settings.douyin_mobile_hook_auto_forward,
    )


def normalize_hook_video(raw: dict[str, Any]) -> dict[str, Any]:
    """Bridge /search videos[] → huoke search-content 单条 video。"""
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    stats = raw.get("statistics") if isinstance(raw.get("statistics"), dict) else {}
    aweme_id = str(raw.get("aweme_id") or raw.get("aid") or raw.get("id") or "").strip()
    share_url = str(raw.get("share_url") or raw.get("video_url") or "").strip()
    if aweme_id:
        share_url = f"https://www.douyin.com/video/{aweme_id}"
    nickname = author.get("nickname") or raw.get("author_name") or raw.get("nickname") or ""
    return {
        "aweme_id": aweme_id,
        "video_url": share_url,
        "title": raw.get("desc") or raw.get("title") or "",
        "author": nickname,
        "author_name": nickname,
        "user_id": str(author.get("uid") or author.get("user_id") or raw.get("user_id") or ""),
        "sec_uid": str(author.get("sec_uid") or raw.get("sec_uid") or ""),
        "like_count": int(stats.get("digg_count") or raw.get("digg_count") or raw.get("like_count") or 0),
        "comment_count": int(stats.get("comment_count") or raw.get("comment_count") or 0),
        "share_count": int(stats.get("share_count") or raw.get("share_count") or 0),
    }


def extract_hook_videos(search_result: dict[str, Any]) -> list[dict[str, Any]]:
    videos = search_result.get("videos")
    if isinstance(videos, list) and videos:
        return [normalize_hook_video(v) for v in videos if isinstance(v, dict)]
    json_data = search_result.get("json_data")
    if isinstance(json_data, str) and json_data.strip():
        try:
            parsed = json.loads(json_data)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            nested = parsed.get("videos") or parsed.get("data")
            if isinstance(nested, list):
                return [normalize_hook_video(v) for v in nested if isinstance(v, dict)]
    return []


async def probe_bridge(settings: Settings) -> dict[str, Any]:
    if not settings.douyin_mobile_hook_enabled:
        return {"ok": False, "ready": False, "error": "mobile_hook_disabled"}
    client = build_hook_client(settings)
    result = await client.probe()
    return {
        "ok": result.ok,
        "ready": result.ready,
        "host": result.host,
        "port": result.port,
        "error": result.error,
        "adapter": (result.payload or {}).get("adapter"),
    }


async def search_videos_via_hook(
    settings: Settings,
    *,
    keyword: str,
    limit: int = 10,
) -> tuple[dict[str, Any], Path | None]:
    """调用 Bridge /search，返回 huoke payload 与可选报告路径。"""
    keyword = str(keyword or "").strip()
    if not keyword:
        raise ValueError("缺少 keyword")
    limit = max(1, min(int(limit), 20))

    client = build_hook_client(settings)
    probe = await client.probe()
    if not probe.ready:
        raise RuntimeError(probe.error or "Bridge 不可达")

    raw = await client.search(keyword, count=limit)
    if not raw.get("success") and raw.get("_http_status", 0) >= 400:
        raise RuntimeError(str(raw.get("error") or f"search HTTP {raw.get('_http_status')}"))

    videos = extract_hook_videos(raw)
    videos = [v for v in videos if v.get("aweme_id")][:limit]
    payload: dict[str, Any] = {
        "platform": PLATFORM,
        "keyword": keyword,
        "search_keyword": keyword,
        "video_count": len(videos),
        "capture_method": CAPTURE_METHOD,
        "source": "mobile_hook",
        "bridge_host": client.host,
        "bridge_port": client.port,
        "videos": videos,
    }
    if not videos:
        payload["diagnostic"] = str(raw.get("error") or "Hook 搜索无结果")
    output: Path | None = None
    if settings.storage_root:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = settings.storage_root / "douyin" / "mobile_hook" / "search"
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"{ts}_{keyword[:32]}.json"
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, output


async def try_search_videos_via_hook(
    settings: Settings,
    *,
    keyword: str,
    limit: int = 10,
) -> tuple[dict[str, Any], Path | None] | None:
    """Bridge 可用则搜索，否则返回 None（由 Playwright 回退）。"""
    if not settings.douyin_mobile_hook_enabled:
        return None
    try:
        probe = await probe_bridge(settings)
        if not probe.get("ready"):
            logger.info("douyin mobile hook skip: %s", probe.get("error"))
            return None
        return await search_videos_via_hook(settings, keyword=keyword, limit=limit)
    except Exception as exc:
        logger.warning("douyin mobile hook search failed: %s", exc)
        return None
