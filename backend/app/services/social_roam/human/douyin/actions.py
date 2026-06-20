from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any

from app.core.antibot import human_click, human_delay, human_type
from app.core.config import Settings
from app.platforms.douyin.js_constants import PLATFORM
from app.platforms.douyin.profile import DouyinProfileTool
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.registry import get_comment_crawler
from app.platforms.douyin.human_guards import assert_douyin_human_ready
from app.services.ui_flow.platforms.douyin.feed_ui import (
    activate_comment_sidebar_on_page,
    is_feed_detail_open,
    is_search_feed_overlay,
    scroll_comment_sidebar_until,
)

_REPLY_BTN_SELECTORS = (
    '[data-e2e="comment-item"] span:has-text("回复")',
    '[data-e2e="comment-item"] button:has-text("回复")',
    '[data-e2e="comment-reply"]',
    'button:has-text("回复")',
    'span:has-text("回复")',
)
_INPUT_SELECTORS = (
    '[data-e2e="comment-input"] div[contenteditable="true"]',
    '[data-e2e="comment-input"] textarea',
    'div.public-DraftEditor-content[contenteditable="true"]',
    'div[contenteditable="true"]',
)
_SEND_SELECTORS = (
    '[data-e2e="comment-post"]',
    'div.comment-input-inner-container button:has-text("发送")',
    'div.comment-input-inner-container span:has-text("发送")',
    'div.commentInput-right-ct button',
    'div.commentInput-right-ct span',
    'button:has-text("发送")',
    'div:has-text("发送")',
)
_PROFILE_AVATAR_SELECTORS = (
    '[data-e2e="comment-item"] div.comment-item-avatar a',
    '[data-e2e="comment-item"] a[href*="/user/"]',
    '[data-e2e="comment-item"] [data-e2e="live-avatar"]',
    'a[href*="/user/"]',
    '[data-e2e="live-avatar"]',
    'div.comment-item-avatar a',
    'img[class*="avatar"]',
)
_FOLLOW_BTN_SELECTORS = (
    '[data-e2e="user-info-follow-btn"]',
    '[data-e2e="user-info-follow"]',
    'button:has-text("关注")',
    '[data-e2e="follow-button"]',
)


async def browse_keyword_comments(
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    keyword: str,
    content_limit: int,
    days: int,
    region: str | None,
    page,
    show_browser: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    store = DouyinSessionStore(settings)
    await assert_douyin_human_ready(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        store=store,
        stage="home",
        goto_home=True,
    )
    backend = get_comment_crawler(settings, PLATFORM, tenant_id, account_id=account_id)
    results, _files, diagnostic, _session_meta = await backend.crawl_keyword_comments(
        keyword=keyword,
        limit=content_limit,
        show_browser=show_browser,
        days=days,
        region=region,
        existing_page=page,
    )
    return results, diagnostic


async def human_reply_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    reply_text: str,
    scroll_rounds: int = 16,
    comment_id: str = "",
    comment_text: str = "",
    parent_comment_id: str = "",
) -> dict[str, Any]:
    if not (comment_id or comment_text):
        return {
            "ok": False,
            "error": "UI 回复需要 comment_text 或 comment_id",
            "capture_method": "douyin_comment_ui_human",
        }
    current_url = (page.url or "").strip()
    on_target = content_url and content_url in current_url
    if content_url and not on_target:
        await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)

    stage = "feed" if await is_feed_detail_open(page) else "video"
    await assert_douyin_human_ready(
        page,
        settings,
        tenant_id=tenant_id,
        stage=stage,
    )
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    await activate_comment_sidebar_on_page(page, settings, tenant_id=tenant_id)
    for _ in range(20):
        if await page.locator('[data-e2e="comment-item"]').count():
            break
        await human_delay(page, settings, tenant_id=tenant_id, profile="poll")

    target = await scroll_comment_sidebar_until(
        page,
        settings,
        tenant_id=tenant_id,
        comment_id=comment_id,
        comment_text=comment_text,
        parent_comment_id=parent_comment_id,
        max_rounds=max(1, scroll_rounds),
    )
    if target is None:
        return {
            "ok": False,
            "error": "分页滚动后仍未找到目标评论"
            + ("（已尝试展开父评论回复）" if parent_comment_id else ""),
            "capture_method": "douyin_comment_ui_human",
            "comment_id": comment_id,
            "parent_comment_id": parent_comment_id or None,
        }

    if stage == "feed":
        await activate_comment_sidebar_on_page(page, settings, tenant_id=tenant_id)
        await human_delay(page, settings, tenant_id=tenant_id, profile="action")

    from app.services.social_roam.human.douyin.reply_warm_publish import (
        _find_reply_btn_in_item,
        _hover_comment_item,
        _locate_reply_input,
    )

    await _hover_comment_item(page, target)
    reply_btn = await _find_reply_btn_in_item(target)
    if reply_btn is None:
        for selector in _REPLY_BTN_SELECTORS:
            candidate = target.locator(selector).first
            if await candidate.count():
                reply_btn = candidate
                break
    if reply_btn is None or not await reply_btn.count():
        return {"ok": False, "error": "未找到回复按钮", "capture_method": "douyin_comment_ui_human"}

    await human_click(page, reply_btn, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="action")

    input_loc = await _locate_reply_input(page, timeout_s=14.0)
    if input_loc is None:
        for selector in _INPUT_SELECTORS:
            candidate = page.locator(selector).last
            try:
                if await candidate.count() and await candidate.is_visible():
                    input_loc = candidate
                    break
            except Exception:
                continue
    if input_loc is None:
        return {"ok": False, "error": "未找到回复输入框", "capture_method": "douyin_comment_ui_human"}

    await human_type(page, input_loc, reply_text, settings, tenant_id=tenant_id)

    post_result: dict[str, Any] = {"ok": False}

    async def on_response(resp) -> None:
        if "comment/publish" not in resp.url:
            return
        try:
            body = await resp.json()
        except Exception:
            return
        code = body.get("status_code")
        if code == 0:
            post_result.update({"ok": True, "status_code": code, "comment": body.get("comment") or {}})

    page.on("response", on_response)
    try:
        send_btn = None
        for selector in _SEND_SELECTORS:
            candidate = page.locator(selector).last
            if await candidate.count():
                send_btn = candidate
                break
        if send_btn is None:
            return {"ok": False, "error": "未找到发送按钮", "capture_method": "douyin_comment_ui_human"}
        await human_click(page, send_btn, settings, tenant_id=tenant_id)
        for _ in range(20):
            if post_result.get("ok"):
                break
            await asyncio.sleep(0.4)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    if post_result.get("ok"):
        return {
            **post_result,
            "capture_method": "douyin_comment_ui_human_type",
            "comment_id": comment_id,
            "content_url": content_url,
        }
    return {
        "ok": False,
        "error": post_result.get("error") or "UI 回复后未捕获成功响应",
        "capture_method": "douyin_comment_ui_human_type",
        "comment_id": comment_id,
    }


async def human_open_profile_from_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str = "",
    comment_text: str = "",
    parent_comment_id: str = "",
    sec_uid: str = "",
    scroll_rounds: int = 8,
    allow_sec_uid_fallback: bool = False,
) -> tuple[Any | None, dict[str, Any]]:
    """从 feed 评论侧栏点头像/链接，在新 tab 打开用户主页。"""
    del sec_uid, allow_sec_uid_fallback  # 保留参数兼容；私信/关注请走 warm_outreach
    on_feed = await is_feed_detail_open(page) or await is_search_feed_overlay(page)
    if not on_feed:
        return None, {
            "ok": False,
            "error": "当前不在 feed 详情/评论侧栏，无法从评论进主页",
            "capture_method": "douyin_profile_from_comment",
        }

    await assert_douyin_human_ready(page, settings, tenant_id=tenant_id, stage="feed")
    target = await scroll_comment_sidebar_until(
        page,
        settings,
        tenant_id=tenant_id,
        comment_id=comment_id,
        comment_text=comment_text,
        parent_comment_id=parent_comment_id,
        max_rounds=max(1, scroll_rounds),
    )
    if target is None:
        return None, {
            "ok": False,
            "error": "分页滚动后仍未找到目标评论"
            + ("（已尝试展开父评论回复）" if parent_comment_id else ""),
            "capture_method": "douyin_profile_from_comment",
            "comment_id": comment_id,
            "parent_comment_id": parent_comment_id or None,
        }

    avatar_link = None
    for selector in _PROFILE_AVATAR_SELECTORS:
        candidate = target.locator(selector).first
        if await candidate.count():
            avatar_link = candidate
            break
    if avatar_link is None or not await avatar_link.count():
        return None, {
            "ok": False,
            "error": "未找到评论用户头像/主页链接",
            "capture_method": "douyin_profile_from_comment",
        }

    context = page.context
    try:
        async with context.expect_page(timeout=20000) as popup:
            await human_click(page, avatar_link, settings, tenant_id=tenant_id)
        profile_page = await popup.value
    except Exception as exc:
        return None, {
            "ok": False,
            "error": f"点击评论头像后未打开新 tab：{exc}",
            "capture_method": "douyin_profile_from_comment",
        }

    try:
        await profile_page.wait_for_load_state("domcontentloaded", timeout=30000)
        await profile_page.wait_for_selector(
            '[data-e2e="user-detail"], [data-e2e="user-info-follow-btn"], button:has-text("关注")',
            state="attached",
            timeout=20000,
        )
    except Exception:
        pass

    store = DouyinSessionStore(settings)
    await assert_douyin_human_ready(
        profile_page,
        settings,
        tenant_id=tenant_id,
        store=store,
        stage="profile",
        goto_home=False,
    )
    return profile_page, {
        "ok": True,
        "profile_url": profile_page.url,
        "capture_method": "douyin_profile_from_comment",
        "comment_id": comment_id,
        "parent_comment_id": parent_comment_id or None,
    }


async def _resolve_profile_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    sec_uid: str,
    profile_page: Any | None,
) -> tuple[Any, str, DouyinProfileTool, DouyinSessionStore]:
    store = DouyinSessionStore(settings)
    profile = DouyinProfileTool(settings, tenant_id, store, account_id=account_id)
    if profile_page is not None:
        work_page = profile_page
        profile_url = work_page.url
    else:
        work_page = page
        await assert_douyin_human_ready(
            work_page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            store=store,
            stage="home",
            goto_home=False,
        )
        profile_url = await profile.open_profile(work_page, sec_uid)
    await assert_douyin_human_ready(
        work_page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        store=store,
        stage="profile",
        goto_home=False,
    )
    return work_page, profile_url, profile, store


_FOLLOW_OK_TEXTS = ("已关注", "互相关注", "已请求")


async def _follow_status_on_page(page) -> tuple[bool, str]:
    for selector in _FOLLOW_BTN_SELECTORS:
        candidate = page.locator(selector).first
        try:
            if not await candidate.count():
                continue
            text = (await candidate.inner_text() or "").strip()
            if any(token in text for token in _FOLLOW_OK_TEXTS):
                return True, text
        except Exception:
            continue
    return False, ""


async def human_follow_user(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    sec_uid: str,
    user_id: str,
    username: str = "",
    profile_page: Any | None = None,
) -> dict[str, Any]:
    work_page, profile_url, _profile, _store = await _resolve_profile_page(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        sec_uid=sec_uid,
        profile_page=profile_page,
    )

    follow_btn = None
    for selector in _FOLLOW_BTN_SELECTORS:
        candidate = work_page.locator(selector).first
        if await candidate.count():
            text = (await candidate.inner_text() or "").strip()
            if any(token in text for token in _FOLLOW_OK_TEXTS):
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_followed",
                    "capture_method": "douyin_follow_ui_human",
                    "profile_url": profile_url,
                    "follow_status_after_text": text,
                }
            follow_btn = candidate
            break
    if follow_btn is None:
        return {
            "ok": False,
            "error": "未找到关注按钮",
            "capture_method": "douyin_follow_ui_human",
            "profile_url": profile_url,
        }

    with contextlib.suppress(Exception):
        await follow_btn.scroll_into_view_if_needed(timeout=5000)
    await human_click(work_page, follow_btn, settings, tenant_id=tenant_id)
    await human_delay(work_page, settings, tenant_id=tenant_id, profile="action")
    await asyncio.sleep(random.uniform(0.8, 1.6))

    ok, verify_text = await _follow_status_on_page(work_page)
    if not ok:
        with contextlib.suppress(Exception):
            verify_text = (await follow_btn.inner_text() or "").strip()
            ok = any(token in verify_text for token in _FOLLOW_OK_TEXTS)
    return {
        "ok": ok,
        "user_id": user_id,
        "sec_uid": sec_uid,
        "username": username,
        "profile_url": profile_url,
        "capture_method": "douyin_follow_ui_human",
        "follow_status_after_text": verify_text,
        "error": None if ok else "点击关注后未检测到已关注状态",
    }


async def human_send_dm(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    sec_uid: str,
    message: str,
    username: str = "",
    profile_page: Any | None = None,
) -> dict[str, Any]:
    """在用户主页通过 UI 点击私信 → 输入 → 发送。"""
    from app.platforms.douyin.dm import DouyinDmTool

    work_page, profile_url, _profile, store = await _resolve_profile_page(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        sec_uid=sec_uid,
        profile_page=profile_page,
    )
    tool = DouyinDmTool(settings, tenant_id, store, account_id=account_id)
    result = await tool.send_message_on_page(
        work_page,
        sec_uid=sec_uid,
        message=message,
        username=username,
    )
    dm = result.get("message") or {}
    ok = bool(dm.get("ok"))
    return {
        "ok": ok,
        "user_id": result.get("user_id"),
        "sec_uid": sec_uid,
        "username": result.get("username") or username,
        "profile_url": profile_url,
        "capture_method": str(dm.get("method") or "douyin_dm_ui_human"),
        "error": None if ok else str(dm.get("error") or dm.get("hint") or "私信发送失败"),
    }
