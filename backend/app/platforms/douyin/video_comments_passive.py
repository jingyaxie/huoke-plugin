"""抖音：按视频地址 UI 被动抓取评论（开侧栏 + 拦截 comment/list + 人类滚动翻页）。"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.platforms.douyin.human_guards import HumanBrowseGuardError, is_captcha_page
from app.platforms.douyin.js_constants import (
    COMMENT_PATH,
    PLATFORM,
    _extract_aweme_id,
    _normalize_comment,
    _try_extract_aweme_id,
)
from app.services.supervisor_outreach import persist_crawl_skill_result
from app.services.ui_flow.platforms.douyin.feed_ui import (
    activate_comment_sidebar_on_page,
    comment_list_end_marker_visible,
    scroll_comment_sidebar_on_page,
    select_latest_comment_sort_on_page,
)


def _normalize_video_url(video_url: str) -> str:
    url = str(video_url or "").strip()
    if not url:
        raise ValueError("缺少 video_url")
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("/"):
        url = f"https://www.douyin.com{url}"
    if not url.startswith("http"):
        aweme_id = _try_extract_aweme_id(url) or url
        if aweme_id.isdigit():
            return f"https://www.douyin.com/video/{aweme_id}"
    return url.split("#")[0]


def _days_cutoff_ts(days: int | None) -> int | None:
    if days is None or int(days) <= 0:
        return None
    now = datetime.now(timezone.utc).timestamp()
    return int(now - int(days) * 86400)


def _merge_captured_pages(captured_pages: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    comments_map: dict[str, dict[str, Any]] = {}
    api_total = 0
    for index, data in enumerate(captured_pages):
        if index == 0:
            api_total = int(data.get("total") or 0)
        for item in data.get("comments") or []:
            row = _normalize_comment(item)
            if row.get("comment_id"):
                comments_map[row["comment_id"]] = row
                for reply in item.get("reply_comment") or []:
                    reply_row = _normalize_comment(reply, parent_comment_id=row["comment_id"])
                    if reply_row.get("comment_id"):
                        comments_map[reply_row["comment_id"]] = reply_row
    return comments_map, api_total


def _comment_in_time_window(row: dict[str, Any], cutoff_ts: int | None) -> bool:
    if cutoff_ts is None:
        return True
    create_time = int(row.get("create_time") or 0)
    if create_time <= 0:
        return True
    return create_time >= cutoff_ts


def _filter_comments_by_days(
    comments_map: dict[str, dict[str, Any]],
    *,
    cutoff_ts: int | None,
    max_comments: int,
) -> list[dict[str, Any]]:
    rows = [row for row in comments_map.values() if _comment_in_time_window(row, cutoff_ts)]
    rows.sort(key=lambda row: int(row.get("create_time") or 0), reverse=True)
    top_rows = [row for row in rows if not row.get("parent_comment_id")][:max_comments]
    kept_ids = {row.get("comment_id") for row in top_rows if row.get("comment_id")}
    kept_ids.update(
        row.get("comment_id")
        for row in rows
        if row.get("parent_comment_id") in kept_ids and row.get("comment_id")
    )
    return [row for row in rows if row.get("comment_id") in kept_ids]


def _newest_top_create_time_in_page(data: dict[str, Any]) -> int | None:
    times = [
        int(item.get("create_time") or 0)
        for item in (data.get("comments") or [])
        if int(item.get("create_time") or 0) > 0
    ]
    return max(times) if times else None


def _should_stop_for_time_window(
    *,
    cutoff_ts: int | None,
    round_idx: int,
    filtered_count: int,
    last_page: dict[str, Any],
    min_scroll_before_time_stop: int = 1,
) -> bool:
    """滚动评论时：若最近一页里「最新的那条」也已早于 cutoff，说明已越过时间窗口。

    在「最新」排序下继续滚只会更旧，应结束当前视频、切换下一个。
    min_scroll_before_time_stop 用于最热排序首页可能是旧热评时的防抖（默认 1 轮）。
    """
    del filtered_count  # 保留参数以兼容既有调用方
    if cutoff_ts is None:
        return False
    if round_idx < min_scroll_before_time_stop:
        return False
    newest_in_last = _newest_top_create_time_in_page(last_page)
    if newest_in_last is None:
        return False
    return newest_in_last < cutoff_ts


def comment_scroll_stop_reason(
    *,
    cutoff_ts: int | None,
    round_idx: int,
    last_page: dict[str, Any],
    captured_pages: list[dict[str, Any]],
    min_scroll_before_time_stop: int = 1,
    comment_days: int | None = None,
) -> str | None:
    """评论翻页结束条件：DOM 无更多标记、超出有效时间窗、或接口无更多分页。"""
    if _should_stop_for_time_window(
        cutoff_ts=cutoff_ts,
        round_idx=round_idx,
        filtered_count=0,
        last_page=last_page,
        min_scroll_before_time_stop=min_scroll_before_time_stop,
    ):
        if comment_days is not None:
            return f"评论已超过 {comment_days} 天有效窗口"
        return "评论已超出有效时间窗口"
    if captured_pages and round_idx > 0 and not int(last_page.get("has_more") or 0):
        return "评论已全部加载（无更多分页）"
    return None


def _last_list_page(captured_pages: list[dict[str, Any]]) -> dict[str, Any]:
    for data in reversed(captured_pages):
        if isinstance(data, dict) and ("has_more" in data or isinstance(data.get("comments"), list)):
            return data
    return {}


def _page_signature(data: dict[str, Any]) -> str:
    return f"{data.get('cursor') or ''}:{len(data.get('comments') or [])}"


async def _wait_page_ready(page) -> None:
    from app.platforms.douyin.human_guards import _wait_page_loaded

    await _wait_page_loaded(page)


def _comment_response_handler(
    captured_pages: list[dict[str, Any]],
    *,
    seen_signatures: set[str],
):
    async def on_response(resp) -> None:
        url = str(resp.url or "")
        if COMMENT_PATH not in url or resp.status >= 400 or "/reply" in url:
            return
        try:
            data = await resp.json()
        except Exception:
            return
        if not isinstance(data, dict):
            return
        sig = _page_signature(data)
        if sig in seen_signatures:
            return
        seen_signatures.add(sig)
        captured_pages.append(data)

    return on_response


async def crawl_video_url_comments(
    page,
    settings,
    *,
    tenant_id: str,
    account_id: str,
    video_url: str,
    max_comments: int = 200,
    days: int | None = None,
    raw_params: dict[str, Any] | None = None,
    db_session: Session | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """打开视频 → 随机停顿 → 点评论 → 拦截 comment/list → 慢速滚侧栏，按 days 窗口结束。"""
    raw_params = dict(raw_params or {})
    video_url = _normalize_video_url(video_url)
    aweme_id = _extract_aweme_id(video_url)
    max_comments = max(1, int(max_comments or 200))
    if days is None and raw_params.get("days") is not None:
        try:
            days = int(raw_params.get("days"))
        except (TypeError, ValueError):
            days = None
    cutoff_ts = _days_cutoff_ts(days)

    captured_pages: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    handler = _comment_response_handler(captured_pages, seen_signatures=seen_signatures)
    page.on("response", handler)

    diagnostic: str | None = None
    stop_reason = ""
    max_scroll_rounds = max(8, min(30, int(raw_params.get("comment_scroll_rounds") or 20)))

    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        await _wait_page_ready(page)
        await asyncio.sleep(random.uniform(0.3, 3.0))

        if await is_captcha_page(page):
            return (
                {"error": "验证码中间页", "status": "failed", "video_url": video_url},
                None,
            )

        if not await activate_comment_sidebar_on_page(page, settings, tenant_id=tenant_id):
            diagnostic = "未能打开评论侧栏，请确认视频页已加载且评论按钮可见"
            return (
                {
                    "platform": PLATFORM,
                    "aweme_id": aweme_id,
                    "video_url": video_url,
                    "total_comments_captured": 0,
                    "error": diagnostic,
                },
                {"videos_processed": 0, "diagnostic": diagnostic},
            )

        await select_latest_comment_sort_on_page(page, settings, tenant_id=tenant_id)
        await asyncio.sleep(random.uniform(1.0, 2.0))

        for round_idx in range(max_scroll_rounds + 1):
            comments_map, api_total = _merge_captured_pages(captured_pages)
            filtered = _filter_comments_by_days(
                comments_map,
                cutoff_ts=cutoff_ts,
                max_comments=max_comments,
            )
            last_page = _last_list_page(captured_pages)

            if await comment_list_end_marker_visible(page):
                stop_reason = "评论已全部加载（暂时没有更多评论）"
                break

            scroll_stop = comment_scroll_stop_reason(
                cutoff_ts=cutoff_ts,
                round_idx=round_idx,
                last_page=last_page,
                captured_pages=captured_pages,
                min_scroll_before_time_stop=1,
                comment_days=days,
            )
            if scroll_stop:
                stop_reason = scroll_stop
                break

            if round_idx >= max_scroll_rounds:
                stop_reason = f"已达安全滚动上限 {max_scroll_rounds} 轮"
                break

            await scroll_comment_sidebar_on_page(
                page,
                settings,
                tenant_id=tenant_id,
                rounds=1,
            )
            await asyncio.sleep(random.uniform(1.5, 3.0))

        comments_map, api_total = _merge_captured_pages(captured_pages)
        filtered = _filter_comments_by_days(
            comments_map,
            cutoff_ts=cutoff_ts,
            max_comments=max_comments,
        )
        top_count = len([r for r in filtered if not r.get("parent_comment_id")])

        payload: dict[str, Any] = {
            "platform": PLATFORM,
            "aweme_id": aweme_id,
            "video_url": video_url,
            "content_id": aweme_id,
            "content_url": video_url,
            "api_total_top_comments": api_total,
            "top_comments_captured": top_count,
            "total_comments_captured": len(filtered),
            "raw_comments_scanned": len(comments_map),
            "capture_method": "video_url_ui_passive",
            "comment_days": days,
            "comments": filtered,
            "keyword_context": {
                "video_url": video_url,
                "capture_mode": "video_url_ui_passive",
                "days": days,
            },
        }
        if stop_reason:
            payload["stop_reason"] = stop_reason
        if not filtered:
            if comments_map and cutoff_ts is not None:
                payload["warning"] = (
                    diagnostic
                    or f"拦截到 {len(comments_map)} 条评论，近 {days} 天内 0 条符合筛选"
                )
            else:
                payload["warning"] = diagnostic or "未拦截到评论数据，请确认已登录且侧栏已展开"

        output = (
            settings.report_output_dir
            / f"comments_{PLATFORM}_{tenant_id}_{aweme_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output_file"] = str(output)

        comments_persisted = 0
        if db_session is not None and filtered:
            try:
                comments_persisted = persist_crawl_skill_result(
                    db_session,
                    settings,
                    tenant_id=tenant_id,
                    platform=PLATFORM,
                    skill_result={"results": [payload]},
                    source_job_id=str(
                        raw_params.get("job_id") or raw_params.get("task_id") or ""
                    ).strip()
                    or None,
                    source_keyword=str(raw_params.get("keyword") or "").strip() or None,
                )
            except Exception:
                pass

        session_meta = {
            "capture_mode": "video_url_ui_passive",
            "videos_processed": 1 if filtered else 0,
            "total_comments_captured": len(filtered),
            "raw_comments_scanned": len(comments_map),
            "comments_persisted": comments_persisted,
            "comment_list_pages": len(captured_pages),
            "has_more_last": int(_last_list_page(captured_pages).get("has_more") or 0),
            "stop_reason": stop_reason,
            "diagnostic": diagnostic,
        }
        job_id = str(raw_params.get("job_id") or raw_params.get("task_id") or "").strip()
        if job_id:
            session_meta["watched_job_id"] = job_id
        return payload, session_meta
    except HumanBrowseGuardError as exc:
        return (
            {"error": str(exc), "status": "failed", "video_url": video_url},
            {"diagnostic": str(exc)},
        )
    finally:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass
