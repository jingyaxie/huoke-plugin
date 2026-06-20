"""抖音触达：入库评论 → 人类节奏进主页 → 关注 + 私信。"""
from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any

from app.core.config import Settings
from app.platforms.douyin.human_guards import assert_douyin_human_ready
from app.platforms.douyin.profile import build_profile_url
from app.platforms.douyin.session import DouyinSessionStore
from app.services.ui_flow.platforms.douyin.feed_ui import (
    activate_comment_sidebar_on_page,
    scroll_comment_sidebar_until,
)
from app.services.social_roam.human.douyin.actions import _FOLLOW_BTN_SELECTORS
from app.services.social_roam.human.douyin.reply_warm_publish import (
    _ensure_on_content_page,
    _hover_comment_item,
    _human_pause,
    _slow_mouse_move,
    _slow_scroll_comment_sidebar,
    _wait_comment_sidebar_ready,
    _warmup_watch_page,
)

_DM_BUTTON_SELECTORS = (
    '[data-e2e="user-detail"] button:has-text("私信")',
    '[data-e2e="user-info-message-btn"]',
    '[data-e2e="user-info"] button:has-text("私信")',
    'button:has-text("私信")',
)

_DM_INPUT_SELECTORS = (
    '[data-e2e="msg-input"] div[contenteditable="true"]',
    '[data-e2e="msg-input"] .editor-kit-container',
    '[data-e2e="im-dialog"] [data-e2e="message-input"]',
    '[data-e2e="im-dialog"] div[contenteditable="true"]',
    '[data-e2e="message-input"]',
)

_DM_SEND_SELECTORS = (
    '[data-e2e="msg-input"] .messageMsgInputinputAction',
    '[data-e2e="msg-input"] button:has-text("发送")',
    '[data-e2e="im-dialog"] button:has-text("发送")',
)

CAPTURE_METHOD = "douyin_warm_outreach_profile"


async def _warmup_browse_profile(page) -> None:
    """主页短暂浏览：停顿 + 轻微滚动。"""
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


_ITEM_PROFILE_LINK_SELECTORS = (
    "div.comment-item-avatar a",
    'a[href*="/user/"]',
    '[data-e2e="live-avatar"]',
    'a[href*="secUid"]',
    'span[class*="nickname"] a',
    'a[href*="douyin.com/user"]',
)


async def _find_avatar_in_item(item):
    for selector in _ITEM_PROFILE_LINK_SELECTORS:
        link = item.locator(selector).first
        try:
            if await link.count() and await link.is_visible():
                return link
        except Exception:
            continue
    with contextlib.suppress(Exception):
        href = await item.evaluate(
            """(el) => {
              const a = el.querySelector('a[href*="/user/"]');
              return a ? a.getAttribute('href') || '' : '';
            }"""
        )
        if href:
            link = item.locator(f'a[href*="{href.split("?")[0]}"]').first
            if await link.count():
                return link
    return None


async def _click_target_comment_profile_link(
    page,
    item,
    settings: Settings,
    *,
    tenant_id: str,
) -> Any | None:
    from app.core.antibot import human_click

    link = await _find_avatar_in_item(item)
    context = page.context
    if link is not None:
        async with context.expect_page(timeout=20000) as popup:
            await human_click(page, link, settings, tenant_id=tenant_id)
        return await popup.value

    has_user_link = await item.evaluate(
        """(el) => Boolean(el.querySelector('a[href*="/user/"]'))"""
    )
    if not has_user_link:
        return None
    async with context.expect_page(timeout=20000) as popup:
        await item.evaluate(
            """(el) => {
              const a = el.querySelector('a[href*="/user/"]');
              if (a) a.click();
            }"""
        )
    return await popup.value


async def _patch_comment_item_profile_href(item, profile_url: str) -> bool:
    """点击前把评论项内主页链接替换为抓取入库的目标 sec_uid。"""
    try:
        return bool(
            await item.evaluate(
                """(el, url) => {
                  const links = el.querySelectorAll('a[href*="/user/"]');
                  if (!links.length) return false;
                  for (const a of links) {
                    a.href = url;
                    a.setAttribute('href', url);
                  }
                  return true;
                }""",
                profile_url,
            )
        )
    except Exception:
        return False


async def _pick_visible_comment_item(page, *, max_scan: int = 12):
    count = 0
    with contextlib.suppress(Exception):
        count = await page.locator('[data-e2e="comment-item"]').count()
    for idx in range(min(count, max_scan)):
        item = page.locator('[data-e2e="comment-item"]').nth(idx)
        try:
            if not await item.count() or not await item.is_visible():
                continue
            has_link = await item.evaluate(
                """(el) => Boolean(el.querySelector('a[href*="/user/"]'))"""
            )
            if has_link:
                return item
        except Exception:
            continue
    return None


async def _ensure_profile_header_visible(page) -> None:
    """暖场滚动后把用户信息栏（关注/私信）滚回视口顶部。"""
    with contextlib.suppress(Exception):
        await page.evaluate("window.scrollTo(0, 0)")
    await _human_pause(min_s=0.5, max_s=0.9)
    for selector in (
        '[data-e2e="user-detail"]',
        '[data-e2e="user-info-follow-btn"]',
        '[data-e2e="user-info"]',
    ):
        loc = page.locator(selector).first
        with contextlib.suppress(Exception):
            if await loc.count():
                await loc.scroll_into_view_if_needed(timeout=5000)
                break


async def _resolve_warm_comment_item(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str,
    comment_text: str,
    scroll_rounds: int,
):
    target_cid = str(comment_id or "").strip()
    target_text = str(comment_text or "").strip()
    if target_cid or target_text:
        item = await scroll_comment_sidebar_until(
            page,
            settings,
            tenant_id=tenant_id,
            comment_id=target_cid,
            comment_text=target_text,
            max_rounds=max(4, scroll_rounds),
        )
        if item is not None:
            return item
    return await _pick_visible_comment_item(page)


async def _open_profile_via_warm_comment_click(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    sec_uid: str,
    comment_id: str = "",
    comment_text: str = "",
    scroll_rounds: int = 12,
) -> tuple[Any | None, str]:
    """暖场滚动评论 → 任选可见评论 → 点击前替换 href 为目标用户 → 点头像进主页。"""
    target_sec = str(sec_uid or "").strip()
    if not target_sec:
        return None, "missing_sec_uid"

    profile_url = build_profile_url(target_sec)
    sidebar_ok = await activate_comment_sidebar_on_page(page, settings, tenant_id=tenant_id)
    if not sidebar_ok:
        sidebar_ok = await _wait_comment_sidebar_ready(page, timeout_s=12.0)
    if not sidebar_ok:
        return None, "sidebar_not_ready"

    await _human_pause(min_s=1.0, max_s=1.7)
    item = await _resolve_warm_comment_item(
        page,
        settings,
        tenant_id=tenant_id,
        comment_id=str(comment_id or ""),
        comment_text=str(comment_text or ""),
        scroll_rounds=scroll_rounds,
    )
    if item is None:
        await _slow_scroll_comment_sidebar(
            page,
            settings,
            tenant_id=tenant_id,
            rounds=random.randint(1, 2),
        )
        await _human_pause(min_s=0.8, max_s=1.4)
        item = await _pick_visible_comment_item(page)
    if item is None:
        return None, "no_comment_with_profile_link"

    await _hover_comment_item(page, item)
    if not await _patch_comment_item_profile_href(item, profile_url):
        return None, "patch_profile_href_failed"

    await _human_pause(min_s=0.7, max_s=1.2)
    try:
        profile_page = await _click_target_comment_profile_link(
            page, item, settings, tenant_id=tenant_id
        )
        if profile_page is None:
            return None, "profile_tab_open_failed"
        with contextlib.suppress(Exception):
            await profile_page.wait_for_load_state("domcontentloaded", timeout=30000)
        if target_sec not in (profile_page.url or ""):
            with contextlib.suppress(Exception):
                await profile_page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
        return profile_page, "warm_click_href_patched"
    except Exception:
        return None, "profile_tab_open_failed"


async def _goto_profile_fallback(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    sec_uid: str,
) -> Any:
    store = DouyinSessionStore(settings)
    profile_url = build_profile_url(sec_uid)
    await page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
    await _human_pause(min_s=1.2, max_s=2.0)
    await assert_douyin_human_ready(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        store=store,
        stage="profile",
        goto_home=False,
    )
    return page


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
            if "已关注" in text or "互相关注" in text:
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
    ok = "已关注" in verify_text or "互相关注" in verify_text
    return {
        "ok": ok,
        "follow_status_after_text": verify_text,
        "error": None if ok else "点击关注后未检测到已关注状态",
    }


async def _dm_input_ready(page) -> bool:
    try:
        return bool(
            await page.evaluate(
                """() => {
                const nodes = document.querySelectorAll(
                  '[data-e2e="msg-input"] [contenteditable="true"], ' +
                  '[data-e2e="im-dialog"] [contenteditable="true"], ' +
                  '[data-e2e="message-input"]'
                );
                for (const el of nodes) {
                  const rect = el.getBoundingClientRect();
                  if (rect.width < 8 || rect.height < 8) continue;
                  const active = document.activeElement === el || el.contains(document.activeElement);
                  const ph = (el.getAttribute('data-placeholder') || el.getAttribute('aria-placeholder') || '').trim();
                  if (active || ph) return true;
                }
                return false;
              }"""
            )
        )
    except Exception:
        return False


async def _locate_dm_input(page, *, timeout_s: float = 14.0):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await _dm_input_ready(page):
            for selector in _DM_INPUT_SELECTORS:
                loc = page.locator(selector).last
                try:
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    continue
        await asyncio.sleep(0.42)
    return None


async def _click_dm_button(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    from app.core.antibot import human_click

    for selector in _DM_BUTTON_SELECTORS:
        btn = page.locator(selector).first
        try:
            if await btn.count() and await btn.is_visible():
                await _human_pause(min_s=0.7, max_s=1.2)
                await human_click(page, btn, settings, tenant_id=tenant_id)
                await _human_pause(min_s=1.2, max_s=2.0)
                return True
        except Exception:
            continue
    with contextlib.suppress(Exception):
        clicked = await page.evaluate(
            """() => {
              const root = document.querySelector('[data-e2e="user-detail"]');
              if (!root) return false;
              const btn = Array.from(root.querySelectorAll('button'))
                .find((el) => (el.textContent || '').includes('私信'));
              if (!btn) return false;
              btn.click();
              return true;
            }"""
        )
        if clicked:
            await _human_pause(min_s=1.2, max_s=2.0)
            return True
    return False


async def _slow_type_dm_input(page, input_loc, text: str) -> None:
    await input_loc.click()
    await _human_pause(min_s=0.5, max_s=0.9)
    is_editable = False
    with contextlib.suppress(Exception):
        is_editable = bool(
            await input_loc.evaluate(
                """(el) => {
                  const node = el.getAttribute('contenteditable') === 'true'
                    ? el
                    : el.querySelector('[contenteditable="true"]') || el;
                  if (node && node.getAttribute('contenteditable') === 'true') {
                    node.focus();
                    return true;
                  }
                  return false;
                }"""
            )
        )
    if not is_editable:
        with contextlib.suppress(Exception):
            await input_loc.fill("")
    else:
        modifier = "Meta" if __import__("platform").system() == "Darwin" else "Control"
        with contextlib.suppress(Exception):
            await page.keyboard.press(f"{modifier}+A")
            await page.keyboard.press("Backspace")
    await _human_pause(min_s=0.3, max_s=0.6)
    for ch in text:
        await page.keyboard.type(ch, delay=random.randint(60, 180))
        if random.random() < 0.08:
            await _human_pause(min_s=0.35, max_s=0.75)


async def _read_dm_input_text(page) -> str:
    for selector in _DM_INPUT_SELECTORS:
        loc = page.locator(selector).last
        try:
            if not await loc.count():
                continue
            value = (await loc.input_value() or "").strip()
            if value:
                return value
            text = (await loc.inner_text() or "").strip()
            if text:
                return text
            editable_text = await loc.evaluate(
                """(el) => {
                  const node = el.getAttribute('contenteditable') === 'true'
                    ? el
                    : el.querySelector('[contenteditable="true"]');
                  return node ? (node.textContent || '').trim() : '';
                }"""
            )
            if editable_text:
                return str(editable_text)
        except Exception:
            continue
    return ""


async def _human_dm_on_profile(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    message: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """点「私信」→ 输入框 → 逐字输入；生产环境点击发送并校验。"""
    text = str(message or "").strip()
    if not text:
        return {"ok": False, "error": "缺少私信文案"}

    if not await _click_dm_button(page, settings, tenant_id=tenant_id):
        return {"ok": False, "error": "未找到或未能点击私信按钮"}

    input_loc = await _locate_dm_input(page, timeout_s=14.0)
    if input_loc is None:
        return {"ok": False, "error": "点击私信后未出现输入框"}

    await _human_pause(min_s=0.6, max_s=1.1)
    await _slow_type_dm_input(page, input_loc, text)
    await _human_pause(min_s=1.0, max_s=1.6)
    typed_preview = (await _read_dm_input_text(page))[:80]
    send_preview = {"text_preview": text[:120], "typed_preview": typed_preview}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "method": "profile_dm_warm_preview",
            "send_preview": send_preview,
        }

    post_result: dict[str, Any] = {"ok": False}

    async def on_response(resp) -> None:
        url = str(resp.url or "")
        if resp.request.method.upper() != "POST":
            return
        if not any(marker in url for marker in ("/im/", "message/send", "msg/send", "send_msg")):
            return
        try:
            body = await resp.json()
        except Exception:
            return
        if isinstance(body, dict) and int(body.get("status_code", -1)) == 0:
            post_result.update({"ok": True, "status_code": 0, "response": body})

    page.on("response", on_response)
    try:
        send_btn = None
        for selector in _DM_SEND_SELECTORS:
            candidate = page.locator(selector).last
            try:
                if await candidate.count() and await candidate.is_visible():
                    send_btn = candidate
                    break
            except Exception:
                continue
        if send_btn is not None:
            from app.core.antibot import human_click

            await human_click(page, send_btn, settings, tenant_id=tenant_id)
        else:
            await page.keyboard.press("Enter")
        for _ in range(20):
            if post_result.get("ok"):
                break
            await asyncio.sleep(0.4)
    finally:
        with contextlib.suppress(Exception):
            page.remove_listener("response", on_response)

    if post_result.get("ok"):
        return {
            "ok": True,
            "dry_run": False,
            "method": "profile_dm_warm_send",
            "send_preview": send_preview,
            "response": post_result.get("response"),
        }

    dialog = page.locator('[data-e2e="im-dialog"]').first
    dialog_text = ""
    with contextlib.suppress(Exception):
        if await dialog.count():
            dialog_text = await dialog.inner_text()
    panel_text = ""
    with contextlib.suppress(Exception):
        panel = page.locator('[data-e2e="msg-input"]').first
        if await panel.count():
            panel_text = await panel.inner_text()
    merged = f"{panel_text}\n{dialog_text}"
    visible = text in merged or bool(typed_preview)
    return {
        "ok": visible,
        "dry_run": False,
        "method": "profile_dm_warm_send",
        "send_preview": send_preview,
        "verified_in_dialog": visible,
        "error": None if visible else "发送后未捕获成功响应且未在对话框中验证到文案",
    }


async def warm_outreach_follow_dm_from_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str = "default",
    content_url: str,
    comment_id: str = "",
    comment_text: str = "",
    sec_uid: str = "",
    user_id: str = "",
    nickname: str = "",
    message: str = "",
    do_follow: bool = True,
    do_dm: bool = True,
    dry_run: bool = False,
    scroll_rounds: int = 12,
) -> dict[str, Any]:
    """视频页暖场 → 评论暖场点击（href 替换为目标 sec_uid）→ 关注 → 私信。"""
    steps: list[str] = []
    profile_page = None
    own_profile = False
    profile_via = ""
    target_sec = str(sec_uid or "").strip()

    if not target_sec:
        return {
            "ok": False,
            "error": "缺少 sec_uid：须来自抓取评论入库数据（comment.raw_data.user.sec_uid）",
            "capture_method": CAPTURE_METHOD,
            "comment_id": comment_id,
        }

    try:
        stage = await _ensure_on_content_page(
            page, settings, tenant_id=tenant_id, content_url=content_url
        )
        steps.append(f"stage={stage}")
        await assert_douyin_human_ready(page, settings, tenant_id=tenant_id, stage=stage)
        if stage == "video":
            await _warmup_watch_page(page)
        else:
            await _human_pause(min_s=1.5, max_s=2.5)

        profile_page, profile_via = await _open_profile_via_warm_comment_click(
            page,
            settings,
            tenant_id=tenant_id,
            sec_uid=target_sec,
            comment_id=comment_id,
            comment_text=comment_text,
            scroll_rounds=scroll_rounds,
        )
        if profile_page is None:
            profile_page = await _goto_profile_fallback(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                sec_uid=target_sec,
            )
            own_profile = True
            profile_via = f"sec_uid_fallback_after_{profile_via}"
        steps.append(f"profile={profile_via}")

        store = DouyinSessionStore(settings)
        await assert_douyin_human_ready(
            profile_page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            store=store,
            stage="profile",
            goto_home=False,
        )
        await _warmup_browse_profile(profile_page)
        await _ensure_profile_header_visible(profile_page)

        from app.services.social_roam.human.douyin.actions import (
            human_follow_user,
            human_send_dm,
        )

        follow_result: dict[str, Any] | None = None
        if do_follow:
            follow_result = await human_follow_user(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                sec_uid=target_sec,
                user_id=str(user_id or ""),
                username=str(nickname or ""),
                profile_page=profile_page,
            )
            if not follow_result.get("ok"):
                return {
                    "ok": False,
                    "error": follow_result.get("error") or "关注失败",
                    "capture_method": CAPTURE_METHOD,
                    "steps": steps + ["follow=failed"],
                    "follow": follow_result,
                    "comment_id": comment_id,
                    "profile_url": profile_page.url,
                }
            steps.append(
                "follow=skipped" if follow_result.get("skipped") else "follow=ok"
            )

        dm_result: dict[str, Any] | None = None
        if do_dm:
            if dry_run:
                dm_result = await _human_dm_on_profile(
                    profile_page,
                    settings,
                    tenant_id=tenant_id,
                    message=message,
                    dry_run=True,
                )
            else:
                sent = await human_send_dm(
                    page,
                    settings,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    sec_uid=target_sec,
                    message=message,
                    username=str(nickname or ""),
                    profile_page=profile_page,
                )
                dm_result = {
                    **sent,
                    "method": sent.get("capture_method") or "profile_dm_ui_human",
                }
            if not dm_result.get("ok"):
                return {
                    "ok": False,
                    "error": dm_result.get("error") or "私信流程失败",
                    "capture_method": CAPTURE_METHOD,
                    "steps": steps + ["dm=failed"],
                    "follow": follow_result,
                    "dm": dm_result,
                    "comment_id": comment_id,
                    "profile_url": profile_page.url,
                }
            steps.append("dm=preview" if dry_run else "dm=sent")

        return {
            "ok": True,
            "dry_run": bool(dry_run and do_dm),
            "capture_method": CAPTURE_METHOD,
            "comment_id": comment_id,
            "comment_text": comment_text[:80] if comment_text else "",
            "sec_uid": sec_uid,
            "user_id": user_id,
            "nickname": nickname,
            "content_url": content_url,
            "profile_url": profile_page.url,
            "profile_via": profile_via,
            "steps": steps,
            "follow": follow_result,
            "dm": dm_result,
        }
    finally:
        if profile_page is not None and not own_profile:
            with contextlib.suppress(Exception):
                await profile_page.close()
