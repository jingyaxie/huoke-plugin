"""抖音评论回复：UI 暖场 → 随机点可见评论「回复」→ 拦截 publish 替换 reply_id（不定位目标评论 DOM）。"""
from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any
from urllib.parse import parse_qs, urlencode

from app.core.config import Settings
from app.platforms.douyin.human_guards import assert_douyin_human_ready
from app.platforms.douyin.js_constants import _extract_aweme_id
from app.services.ui_flow.platforms.douyin.feed_ui import (
    activate_comment_sidebar_on_page,
    is_feed_detail_open,
)

_WARM_REPLY_INPUT_SELECTORS = (
    '[data-e2e="comment-input"] div.public-DraftEditor-content[contenteditable="true"]',
    '[data-e2e="comment-input"] [contenteditable="true"]',
    ".comment-input-inner-container div.public-DraftEditor-content[contenteditable='true']",
)

_ITEM_REPLY_BTN_SELECTORS = (
    '[data-e2e="comment-reply"]',
    'span:has-text("回复")',
    'button:has-text("回复")',
)

_SEND_SELECTORS = (
    '[data-e2e="comment-post"]',
    'div.comment-input-inner-container button:has-text("发送")',
    'div.comment-input-inner-container span:has-text("发送")',
    'div.commentInput-right-ct button',
    'div.commentInput-right-ct span',
    'button:has-text("发送")',
)

CAPTURE_METHOD = "douyin_comment_warm_publish"
CAPTURE_METHOD_DRY = "douyin_comment_warm_publish_dry_run"


async def _human_pause(*, min_s: float = 1.0, max_s: float = 1.8) -> None:
    """系统 Chrome 下 antibot delay 无效，暖场必须显式等待。"""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def _slow_mouse_move(page, x: float, y: float) -> None:
    with contextlib.suppress(Exception):
        await page.mouse.move(x, y, steps=random.randint(14, 24))


async def _warmup_watch_page(page) -> None:
    """进入视频页后先「看一会儿」：停顿 + 鼠标在播放区轻微移动。"""
    vp = page.viewport_size or {"width": 1440, "height": 900}
    await _human_pause(min_s=2.0, max_s=3.5)
    for _ in range(random.randint(2, 4)):
        x = random.uniform(vp["width"] * 0.28, vp["width"] * 0.72)
        y = random.uniform(vp["height"] * 0.22, vp["height"] * 0.62)
        await _slow_mouse_move(page, x, y)
        await _human_pause(min_s=0.7, max_s=1.4)


async def _wait_comment_sidebar_ready(page, *, timeout_s: float = 12.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        try:
            if await page.locator('[data-e2e="comment-item"]').count() > 0:
                return True
            if await page.locator("text=全部评论").count() > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.45)
    return False


async def _slow_scroll_comment_sidebar(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 2,
) -> None:
    from app.services.ui_flow.platforms.douyin.feed_ui import (
        COMMENT_SIDEBAR_SCROLL_JS,
        _wheel_comment_list_area,
    )

    for i in range(max(1, rounds)):
        await _human_pause(min_s=0.9, max_s=1.6)
        with contextlib.suppress(Exception):
            await page.evaluate(COMMENT_SIDEBAR_SCROLL_JS)
        await _human_pause(min_s=0.5, max_s=0.9)
        with contextlib.suppress(Exception):
            await _wheel_comment_list_area(page, settings, tenant_id=tenant_id)
        if i + 1 < rounds:
            await _human_pause(min_s=1.0, max_s=1.8)


def _patch_publish_post_data(
    post_data: str,
    *,
    aweme_id: str,
    comment_id: str,
    reply_text: str,
) -> str:
    """拦截 comment/publish 时把 reply_id/text 替换为入库目标（类比 warm_outreach 的 href patch）。"""
    pairs = parse_qs(post_data or "", keep_blank_values=True)
    flat = {key: (values[0] if values else "") for key, values in pairs.items()}
    flat["aweme_id"] = aweme_id
    flat["reply_id"] = comment_id
    flat["text"] = reply_text
    flat.setdefault("text_extra", "")
    flat.setdefault("is_self_see", "0")
    flat.setdefault("reply_to_reply_id", "0")
    return urlencode(flat)


async def _ensure_on_content_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
) -> str:
    current = (page.url or "").strip()
    if content_url and content_url in current:
        return "feed" if await is_feed_detail_open(page) else "video"
    if await is_feed_detail_open(page):
        return "feed"
    if content_url:
        await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)
        await _human_pause(min_s=1.0, max_s=1.6)
    return "feed" if await is_feed_detail_open(page) else "video"


async def _hover_comment_item(page, item) -> None:
    """回复按钮通常 hover 评论后才出现。"""
    try:
        box = await item.bounding_box()
        if not box:
            return
        x = box["x"] + box["width"] * 0.55
        y = box["y"] + box["height"] * 0.55
        await _slow_mouse_move(page, x, y)
        await _human_pause(min_s=0.6, max_s=1.1)
    except Exception:
        pass


async def _find_reply_btn_in_item(item):
    for selector in _ITEM_REPLY_BTN_SELECTORS:
        btn = item.locator(selector).first
        try:
            if await btn.count() and await btn.is_visible():
                return btn
        except Exception:
            continue
    return None


async def _reply_input_ready(page) -> bool:
    try:
        return bool(
            await page.evaluate(
                """() => {
                const nodes = document.querySelectorAll(
                  '[data-e2e="comment-input"] [contenteditable="true"], ' +
                  '.comment-input-inner-container [contenteditable="true"]'
                );
                for (const el of nodes) {
                  const rect = el.getBoundingClientRect();
                  if (rect.width < 8 || rect.height < 8) continue;
                  const ph = (el.getAttribute('data-placeholder') || el.getAttribute('aria-placeholder') || '').trim();
                  const active = document.activeElement === el || el.contains(document.activeElement);
                  if (active || ph.includes('回复')) return true;
                }
                return false;
              }"""
            )
        )
    except Exception:
        return False


async def _locate_reply_input(page, *, timeout_s: float = 14.0):
    """点「回复」后才会出现的输入框（非底部发评框）。"""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await _reply_input_ready(page):
            for selector in _WARM_REPLY_INPUT_SELECTORS:
                loc = page.locator(selector).last
                try:
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    continue
        await asyncio.sleep(0.42)
    return None


async def _click_reply_on_random_visible_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    """打开评论侧栏 → 随机 hover 一条可见评论 → 点「回复」→ 等输入框出现。"""
    from app.core.antibot import human_click

    await _human_pause(min_s=1.0, max_s=1.8)
    sidebar_ok = await activate_comment_sidebar_on_page(page, settings, tenant_id=tenant_id)
    if not sidebar_ok:
        sidebar_ok = await _wait_comment_sidebar_ready(page, timeout_s=12.0)
    if not sidebar_ok:
        return False

    await _human_pause(min_s=1.2, max_s=2.0)
    await _wait_comment_sidebar_ready(page)
    await _human_pause(min_s=0.8, max_s=1.4)
    await _slow_scroll_comment_sidebar(
        page,
        settings,
        tenant_id=tenant_id,
        rounds=random.randint(1, 2),
    )
    await _human_pause(min_s=1.0, max_s=1.7)

    item_count = 0
    with contextlib.suppress(Exception):
        item_count = await page.locator('[data-e2e="comment-item"]').count()

    indices = list(range(min(item_count, 10)))
    random.shuffle(indices)
    for idx in indices:
        item = page.locator('[data-e2e="comment-item"]').nth(idx)
        try:
            if not await item.count() or not await item.is_visible():
                continue
            await _hover_comment_item(page, item)
            reply_btn = await _find_reply_btn_in_item(item)
            if reply_btn is None:
                continue
            await _human_pause(min_s=0.5, max_s=0.9)
            await human_click(page, reply_btn, settings, tenant_id=tenant_id)
            await _human_pause(min_s=1.0, max_s=1.8)
            if await _locate_reply_input(page, timeout_s=12.0):
                return True
        except Exception:
            continue
    return False


async def _slow_type_comment_input(page, input_loc, text: str) -> None:
    """逐字输入（系统 Chrome 下 human_type 会瞬间 fill）。"""
    await input_loc.click()
    await _human_pause(min_s=0.5, max_s=0.9)
    is_editable = False
    with contextlib.suppress(Exception):
        is_editable = bool(
            await input_loc.evaluate(
                """(el) => {
                  const node = el.getAttribute('contenteditable') === 'true'
                    ? el
                    : el.querySelector('[contenteditable="true"]');
                  if (!node) return false;
                  node.focus();
                  return true;
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


async def _type_into_comment_input(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    reply_text: str,
) -> bool:
    from app.core.antibot import antibot_suppressed_for_page, human_type

    input_loc = await _locate_reply_input(page, timeout_s=12.0)
    if input_loc is None:
        return False
    await _human_pause(min_s=0.6, max_s=1.1)
    if antibot_suppressed_for_page(page):
        await _slow_type_comment_input(page, input_loc, reply_text)
    else:
        await human_type(page, input_loc, reply_text, settings, tenant_id=tenant_id)
    await _human_pause(min_s=1.0, max_s=1.8)
    return True


async def _read_comment_input_text(page) -> str:
    for selector in _WARM_REPLY_INPUT_SELECTORS:
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


async def _install_publish_interceptor(
    page,
    *,
    dry_run: bool,
    aweme_id: str,
    comment_id: str,
    reply_text: str,
) -> None:
    async def _handle(route) -> None:
        if "comment/publish" not in (route.request.url or ""):
            await route.continue_()
            return
        if dry_run:
            await route.abort("blockedbyclient")
            return
        patched = _patch_publish_post_data(
            route.request.post_data or "",
            aweme_id=aweme_id,
            comment_id=comment_id,
            reply_text=reply_text,
        )
        await route.continue_(post_data=patched)

    try:
        await page.route("**/*", _handle)
    except Exception as exc:
        err = str(exc)
        if "setCacheDisabled" in err or "wasn't found" in err:
            return
        raise


async def _remove_publish_interceptor(page) -> None:
    with contextlib.suppress(Exception):
        await page.unroute("**/*")


async def _click_send_and_wait_publish(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    publish_result: dict[str, Any],
    timeout_s: float = 14.0,
) -> bool:
    from app.core.antibot import human_click

    send_btn = None
    for selector in _SEND_SELECTORS:
        candidate = page.locator(selector).last
        try:
            if await candidate.count() and await candidate.is_visible():
                send_btn = candidate
                break
        except Exception:
            continue
    if send_btn is None:
        publish_result["error"] = "未找到发送按钮"
        return False

    await _human_pause(min_s=0.5, max_s=0.9)
    await human_click(page, send_btn, settings, tenant_id=tenant_id)

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if publish_result.get("ok"):
            return True
        if publish_result.get("error"):
            return False
        await asyncio.sleep(0.35)
    publish_result.setdefault("error", "UI 发送后未捕获 comment/publish 成功响应")
    return False


async def warm_publish_reply_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    comment_id: str,
    reply_text: str,
    aweme_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """UI 暖场 → 随机点回复 → 点发送；route 拦截 publish 并替换 reply_id。dry_run 仅预览不发帖。"""
    text = str(reply_text or "").strip()
    target_cid = str(comment_id or "").strip()
    if not target_cid:
        return {"ok": False, "error": "缺少 comment_id", "capture_method": CAPTURE_METHOD}
    if not text:
        return {"ok": False, "error": "缺少 reply_text", "capture_method": CAPTURE_METHOD}

    resolved_aweme = str(aweme_id or "").strip()
    if not resolved_aweme and content_url:
        with contextlib.suppress(ValueError):
            resolved_aweme = _extract_aweme_id(content_url)
    if not resolved_aweme:
        return {"ok": False, "error": "缺少 aweme_id", "capture_method": CAPTURE_METHOD}

    publish_result: dict[str, Any] = {"ok": False}

    async def on_response(resp) -> None:
        if "comment/publish" not in (resp.url or ""):
            return
        try:
            body = await resp.json()
        except Exception:
            return
        status_code = body.get("status_code")
        if status_code == 0:
            publish_result.update(
                {
                    "ok": True,
                    "status_code": status_code,
                    "status_msg": body.get("status_msg") or "",
                    "comment": body.get("comment") or {},
                }
            )
        else:
            publish_result["error"] = (
                body.get("status_msg")
                or body.get("error")
                or f"status_code={status_code}"
            )

    page.on("response", on_response)
    await _install_publish_interceptor(
        page,
        dry_run=dry_run,
        aweme_id=resolved_aweme,
        comment_id=target_cid,
        reply_text=text,
    )
    steps: list[str] = []
    try:
        stage = await _ensure_on_content_page(
            page, settings, tenant_id=tenant_id, content_url=content_url
        )
        steps.append(f"stage={stage}")
        await assert_douyin_human_ready(page, settings, tenant_id=tenant_id, stage=stage)
        if stage == "video":
            await _warmup_watch_page(page)
        else:
            await _human_pause(min_s=1.8, max_s=2.8)

        reply_opened = await _click_reply_on_random_visible_comment(
            page, settings, tenant_id=tenant_id
        )
        if not reply_opened:
            return {
                "ok": False,
                "error": "未能点击评论回复并打开输入框",
                "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
                "steps": steps,
            }
        steps.append("input=reply_button")

        if not await _type_into_comment_input(
            page, settings, tenant_id=tenant_id, reply_text=text
        ):
            return {
                "ok": False,
                "error": "未能输入回复文案",
                "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
                "steps": steps,
            }
        steps.append("typed")
        typed_preview = (await _read_comment_input_text(page))[:80]
        would_publish = {
            "aweme_id": resolved_aweme,
            "reply_id": target_cid,
            "text_preview": text[:120],
            "intercept": "comment/publish route patch reply_id",
        }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "capture_method": CAPTURE_METHOD_DRY,
                "comment_id": target_cid,
                "aweme_id": resolved_aweme,
                "content_url": content_url,
                "page_url": page.url,
                "steps": steps,
                "typed_preview": typed_preview,
                "would_publish": would_publish,
                "diagnostic": "dry_run：已完成暖场与输入，未点击发送",
            }

        sent_ok = await _click_send_and_wait_publish(
            page,
            settings,
            tenant_id=tenant_id,
            publish_result=publish_result,
        )
        steps.append("send_clicked")
        if not sent_ok:
            return {
                "ok": False,
                "error": publish_result.get("error") or "comment_publish_failed",
                "capture_method": CAPTURE_METHOD,
                "comment_id": target_cid,
                "steps": steps,
                "would_publish": would_publish,
            }
        return {
            "ok": True,
            "dry_run": False,
            "capture_method": CAPTURE_METHOD,
            "comment_id": target_cid,
            "aweme_id": resolved_aweme,
            "content_url": content_url,
            "page_url": page.url,
            "steps": steps,
            "reply": publish_result,
        }
    finally:
        await _remove_publish_interceptor(page)
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
