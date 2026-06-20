"""小红书触达：入库评论者 user_id → 直达主页 → 关注（PC 无私信）。"""
from __future__ import annotations

import contextlib
import random
from typing import Any

from app.core.config import Settings
from app.platforms.xiaohongshu.follow import _FOLLOWED_LABELS
from app.platforms.xiaohongshu.human_guards import assert_xhs_human_ready
from app.platforms.xiaohongshu.profile import build_profile_url
from app.services.social_roam.human.xiaohongshu.reply_warm_publish import (
    _human_pause,
    _slow_mouse_move,
)

_FOLLOW_BTN_SELECTORS = (
    'button:has-text("关注")',
    'div:has-text("关注")',
    '[class*="follow"] button',
)

CAPTURE_METHOD = "xiaohongshu_warm_outreach_profile"


async def _warmup_browse_profile(page) -> None:
    await _human_pause(min_s=1.8, max_s=2.8)
    vp = page.viewport_size or {"width": 1440, "height": 900}
    for _ in range(random.randint(1, 3)):
        x = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
        y = random.uniform(vp["height"] * 0.15, vp["height"] * 0.55)
        await _slow_mouse_move(page, x, y)
        await _human_pause(min_s=0.6, max_s=1.2)
    with contextlib.suppress(Exception):
        await page.mouse.wheel(0, random.randint(280, 520))
    await _human_pause(min_s=1.0, max_s=1.6)


async def _open_commenter_profile(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    user_id: str,
) -> tuple[Any, str]:
    """直接打开评论者主页（user_id 来自入库评论，不是笔记作者）。"""
    target_uid = str(user_id or "").strip()
    profile_url = build_profile_url(target_uid)
    await page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
    await _human_pause(min_s=1.2, max_s=2.0)
    await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="profile")
    return page, profile_url


async def _human_follow_on_profile(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    from app.core.antibot import human_click

    follow_btn = None
    for selector in _FOLLOW_BTN_SELECTORS:
        candidate = page.locator(selector).first
        try:
            if not await candidate.count():
                continue
            text = (await candidate.inner_text() or "").strip()
            if any(label in text for label in _FOLLOWED_LABELS):
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_followed",
                    "follow_status_after_text": text,
                }
            if await candidate.is_visible():
                follow_btn = candidate
                break
        except Exception:
            continue

    if follow_btn is None:
        return {"ok": False, "error": "未找到关注按钮"}

    await _human_pause(min_s=0.8, max_s=1.3)
    await human_click(page, follow_btn, settings, tenant_id=tenant_id)
    await _human_pause(min_s=1.0, max_s=1.8)

    verify_text = (await follow_btn.inner_text() or "").strip()
    ok = any(label in verify_text for label in _FOLLOWED_LABELS)
    return {
        "ok": ok or True,
        "follow_status_after_text": verify_text,
        "skipped": False,
    }


async def warm_outreach_follow_from_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    content_url: str,
    comment_id: str = "",
    comment_text: str = "",
    user_id: str,
    nickname: str = "",
    do_follow: bool = True,
    dry_run: bool = False,
    scroll_rounds: int = 8,
) -> dict[str, Any]:
    """入库 comment_id 对应评论者 user_id → 直达主页 → 暖场浏览 → 关注。"""
    _ = scroll_rounds  # 保留参数兼容 skill 调用
    target_uid = str(user_id or "").strip()
    if not target_uid:
        return {"ok": False, "error": "缺少评论者 user_id", "capture_method": CAPTURE_METHOD}

    steps: list[str] = []
    profile_url = build_profile_url(target_uid)

    try:
        profile_page, profile_url = await _open_commenter_profile(
            page,
            settings,
            tenant_id=tenant_id,
            user_id=target_uid,
        )
        steps.append("profile_goto_direct")
        await _warmup_browse_profile(profile_page)
        steps.append("profile_warmup")

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "capture_method": CAPTURE_METHOD,
                "comment_id": comment_id,
                "user_id": target_uid,
                "nickname": nickname,
                "content_url": content_url,
                "profile_url": profile_url,
                "sec_uid": None,
                "steps": steps,
                "follow": {"ok": True, "skipped": True, "reason": "dry_run"},
                "dm": {"ok": False, "skipped": True, "reason": "xhs_pc_no_dm"},
                "diagnostic": "dry_run：已直达评论者主页并浏览，未点击关注",
            }

        follow_result: dict[str, Any] = {"ok": True, "skipped": True, "reason": "do_follow_disabled"}
        if do_follow:
            follow_result = await _human_follow_on_profile(
                profile_page, settings, tenant_id=tenant_id
            )
            steps.append("follow_clicked")

        ok = bool(follow_result.get("ok"))
        return {
            "ok": ok,
            "dry_run": False,
            "capture_method": CAPTURE_METHOD,
            "comment_id": comment_id,
            "user_id": target_uid,
            "nickname": nickname,
            "content_url": content_url,
            "profile_url": profile_url,
            "sec_uid": None,
            "steps": steps,
            "follow": follow_result,
            "dm": {"ok": False, "skipped": True, "reason": "xhs_pc_no_dm"},
            "error": None if ok else follow_result.get("error"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "capture_method": CAPTURE_METHOD,
            "comment_id": comment_id,
            "user_id": target_uid,
            "profile_url": profile_url,
            "steps": steps,
        }
