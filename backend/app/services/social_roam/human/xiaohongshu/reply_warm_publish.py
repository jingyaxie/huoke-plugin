"""小红书评论回复：A 定位目标评论回复 → C 随机评论+patch 降级 → 失败明确报错。"""
from __future__ import annotations

import asyncio
import contextlib
import json
import random
from typing import Any

from app.core.config import Settings
from app.platforms.xiaohongshu.human_guards import assert_xhs_human_ready
from app.platforms.xiaohongshu.utils import extract_note_id
from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
    activate_comments_on_detail,
    is_note_detail_open,
    open_note_for_ui_action,
    scroll_comment_list_in_detail,
)
from app.services.ui_flow.platforms.xiaohongshu.note_ui import trigger_comment_panel

_REPLY_POPUP_MARK = "data-huoke-reply-popup"
_REPLY_INPUT_MARK = "data-huoke-reply-input"

_FIND_REPLY_COMPOSE_JS = """
() => {
  document.querySelectorAll('[data-huoke-reply-popup="1"], [data-huoke-reply-input="1"]').forEach((el) => {
    el.removeAttribute('data-huoke-reply-popup');
    el.removeAttribute('data-huoke-reply-input');
  });
  const isVisible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 20 && r.height > 12 && r.bottom > 0 && r.top < innerHeight;
  };
  const sendNodes = [...document.querySelectorAll('button, div, span')].filter((el) => {
    return (el.textContent || '').trim() === '发送' && isVisible(el);
  });
  for (const send of sendNodes) {
    let root = send.parentElement;
    for (let depth = 0; depth < 12 && root; depth += 1) {
      const text = (root.textContent || '').trim();
      const hasCancel = [...root.querySelectorAll('button, div, span')].some(
        (el) => (el.textContent || '').trim() === '取消'
      );
      const hasReplyTitle = /回复\\s+\\S/.test(text.slice(0, 48));
      const input = root.querySelector('[contenteditable="true"], textarea');
      if (hasCancel && hasReplyTitle && input && isVisible(input)) {
        root.setAttribute('data-huoke-reply-popup', '1');
        input.setAttribute('data-huoke-reply-input', '1');
        input.focus();
        input.click();
        return true;
      }
      root = root.parentElement;
    }
  }
  return false;
}
"""

_IS_REPLY_COMPOSE_OPEN_JS = """
() => Boolean(document.querySelector('[data-huoke-reply-input="1"], [data-huoke-reply-popup="1"] [contenteditable="true"]'))
"""

_ITEM_REPLY_BTN_SELECTORS = (
    ".reply.icon-container",
    ".reply",
)

CAPTURE_METHOD = "xiaohongshu_comment_warm_publish"
CAPTURE_METHOD_DRY = "xiaohongshu_comment_warm_publish_dry_run"
CAPTURE_METHOD_FALLBACK = "xiaohongshu_comment_warm_publish_fallback"

_COMMENT_ITEM_SELECTORS = (
    ".comment-item",
    ".parent-comment",
    ".note-comment-item",
)

_POPUP_INPUT_SELECTORS = (
    '[contenteditable="true"]',
    "textarea",
)

_POPUP_SEND_SELECTORS = (
    'button:has-text("发送")',
    'div:has-text("发送")',
    'span:has-text("发送")',
)


async def _human_pause(*, min_s: float = 1.0, max_s: float = 1.8) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


async def _slow_mouse_move(page, x: float, y: float) -> None:
    with contextlib.suppress(Exception):
        await page.mouse.move(x, y, steps=random.randint(14, 24))


async def _page_note_accessible(page) -> bool:
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    url = page.url or ""
    if "页面不见了" in title or "/404" in url or "暂时无法浏览" in url:
        return False
    return True


async def _warmup_note_page(page) -> None:
    vp = page.viewport_size or {"width": 1440, "height": 900}
    await _human_pause(min_s=2.0, max_s=3.5)
    for _ in range(random.randint(2, 4)):
        x = random.uniform(vp["width"] * 0.28, vp["width"] * 0.72)
        y = random.uniform(vp["height"] * 0.22, vp["height"] * 0.62)
        await _slow_mouse_move(page, x, y)
        await _human_pause(min_s=0.7, max_s=1.4)


async def _wait_comment_panel_ready(page, *, timeout_s: float = 12.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        try:
            for sel in _COMMENT_ITEM_SELECTORS:
                if await page.locator(sel).count() > 0:
                    return True
            if await page.locator('span:has-text("条评论")').count() > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.45)
    return False


async def _ensure_on_note_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    note_id: str = "",
    note_meta: dict[str, Any] | None = None,
) -> str:
    """先进笔记详情再评论；探索首页不误判为浮层，不在首页滚评论。"""
    from app.services.ui_flow.platforms.xiaohongshu.feed_ui import (
        _on_explore_home_page,
        _note_detail_matches_id,
    )

    resolved_id = str(note_id or "").strip()
    if not resolved_id and content_url:
        with contextlib.suppress(ValueError):
            resolved_id = extract_note_id(content_url)

    if (
        resolved_id
        and not _on_explore_home_page(page.url)
        and await is_note_detail_open(page)
        and await _page_note_accessible(page)
        and await _note_detail_matches_id(page, resolved_id)
    ):
        await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
        await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
        return "note"

    if content_url and not _on_explore_home_page(page.url):
        with contextlib.suppress(Exception):
            await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)
            await _human_pause(min_s=1.0, max_s=1.6)
        if (
            await is_note_detail_open(page)
            and await _page_note_accessible(page)
            and (not resolved_id or await _note_detail_matches_id(page, resolved_id))
        ):
            await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
            await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
            return "note"

    opened = await open_note_for_ui_action(
        page,
        settings,
        tenant_id=tenant_id,
        content_url=content_url,
        note_id=resolved_id,
        note_meta=note_meta,
    )
    if not opened.get("ok") and content_url:
        with contextlib.suppress(Exception):
            await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)
            await _human_pause(min_s=2.0, max_s=3.0)
        if await _page_note_accessible(page):
            await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
            await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
            return "note_goto"
    if not opened.get("ok"):
        raise RuntimeError("无法打开笔记详情")
    await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
    return "note"


async def _hover_comment_item(page, item) -> None:
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


async def _clear_reply_popup_mark(page) -> None:
    with contextlib.suppress(Exception):
        await page.evaluate(
            """() => {
              document.querySelectorAll('[data-huoke-reply-popup="1"], [data-huoke-reply-input="1"]').forEach((el) => {
                el.removeAttribute('data-huoke-reply-popup');
                el.removeAttribute('data-huoke-reply-input');
              });
            }"""
        )


async def _mark_reply_compose(page) -> bool:
    with contextlib.suppress(Exception):
        return bool(await page.evaluate(_FIND_REPLY_COMPOSE_JS))
    return False


async def _reply_compose_open(page) -> bool:
    if await _mark_reply_compose(page):
        return True
    with contextlib.suppress(Exception):
        return bool(await page.evaluate(_IS_REPLY_COMPOSE_OPEN_JS))
    return False


def _reply_input_locator(page):
    return page.locator(f'[{_REPLY_INPUT_MARK}="1"]').first


def _reply_popup_locator(page):
    return page.locator(f'[{_REPLY_POPUP_MARK}="1"]').first


async def _focus_reply_input_in_popup(page, input_loc) -> bool:
    """点击弹层输入框并 focus（对应「回复 xxx」pop 内光标）。"""
    with contextlib.suppress(Exception):
        await input_loc.click()
    await _human_pause(min_s=0.4, max_s=0.7)
    try:
        return bool(
            await input_loc.evaluate(
                """(el) => {
                  const node = el.getAttribute('contenteditable') === 'true'
                    ? el
                    : el.querySelector('[contenteditable="true"]');
                  if (!node) return false;
                  node.focus();
                  node.click();
                  return document.activeElement === node || node.contains(document.activeElement);
                }"""
            )
        )
    except Exception:
        return False


async def _slow_type_reply_input(page, input_loc, text: str) -> None:
    """逐字输入：先 focus 弹层输入框，再 keyboard.type。"""
    await _focus_reply_input_in_popup(page, input_loc)
    modifier = "Meta" if __import__("platform").system() == "Darwin" else "Control"
    with contextlib.suppress(Exception):
        await page.keyboard.press(f"{modifier}+A")
        await page.keyboard.press("Backspace")
    await _human_pause(min_s=0.3, max_s=0.5)
    for ch in text:
        await page.keyboard.type(ch, delay=random.randint(60, 180))
        if random.random() < 0.08:
            await _human_pause(min_s=0.25, max_s=0.5)


async def _wait_reply_popup(page, *, timeout_s: float = 12.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await _reply_compose_open(page):
            return True
        await asyncio.sleep(0.25)
    return False


async def _locate_reply_input_in_popup(page):
    if await _mark_reply_compose(page):
        loc = _reply_input_locator(page)
        try:
            if await loc.count() and await loc.is_visible():
                return loc
        except Exception:
            pass
    return None


async def _locate_send_in_popup(page):
    if not await _mark_reply_compose(page):
        return None
    popup = _reply_popup_locator(page)
    for selector in _POPUP_SEND_SELECTORS:
        loc = popup.locator(selector).last
        try:
            if await loc.count() and await loc.is_visible():
                return loc
        except Exception:
            continue
    return None


async def _pick_random_comment_item(page):
    """任取一条可见 .comment-item（fallback C 用）。"""
    loc = page.locator(".comment-item")
    try:
        count = await loc.count()
    except Exception:
        return None
    if count <= 0:
        return None
    indices = list(range(min(count, 12)))
    random.shuffle(indices)
    for idx in indices:
        item = loc.nth(idx)
        try:
            if await item.count() and await item.is_visible():
                return item
        except Exception:
            continue
    return None


async def _patch_comment_item_reply_context(
    item,
    *,
    target_comment_id: str,
    parent_comment_id: str = "",
) -> bool:
    """点击回复前：在可见评论节点上写入目标 comment_id（供前端/降级 route 对齐）。"""
    target = str(target_comment_id or "").strip()
    parent = str(parent_comment_id or "").strip()
    if not target:
        return False
    try:
        return bool(
            await item.evaluate(
                """(el, payload) => {
                  const targetId = String(payload.targetId || '').trim();
                  const parentId = String(payload.parentId || '').trim();
                  if (!targetId) return false;
                  for (const node of el.querySelectorAll('[id^="comment-"]')) {
                    node.id = `comment-${targetId}`;
                  }
                  el.setAttribute('data-huoke-reply-target-id', targetId);
                  if (parentId) {
                    el.setAttribute('data-huoke-reply-parent-id', parentId);
                  }
                  const btn = el.querySelector('.reply.icon-container, .reply');
                  if (btn) {
                    btn.setAttribute('data-target-comment-id', targetId);
                    if (parentId) btn.setAttribute('data-parent-comment-id', parentId);
                  }
                  return true;
                }""",
                {"targetId": target, "parentId": parent},
            )
        )
    except Exception:
        return False


async def _expand_sub_comments_for_parent(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    parent_comment_id: str,
) -> bool:
    """滚到父评论并点击「展开/条回复」。"""
    from app.core.antibot import human_click

    parent_id = str(parent_comment_id or "").strip()
    if not parent_id:
        return False

    parent_item = await _find_target_comment_item(page, comment_id=parent_id, comment_text="")
    if parent_item is None:
        return False

    with contextlib.suppress(Exception):
        await parent_item.scroll_into_view_if_needed(timeout=5000)
    await _hover_comment_item(page, parent_item)
    await _human_pause(min_s=0.4, max_s=0.7)

    for selector in (
        'span:has-text("条回复")',
        'div:has-text("条回复")',
        'button:has-text("条回复")',
        'span:has-text("展开")',
        'text=/展开.*回复/',
        'text=/\\d+\\s*条回复/',
    ):
        loc = parent_item.locator(selector).first
        try:
            if await loc.count() and await loc.is_visible():
                await human_click(page, loc, settings, tenant_id=tenant_id)
                await _human_pause(min_s=0.8, max_s=1.4)
                return True
        except Exception:
            continue

    with contextlib.suppress(Exception):
        return bool(
            await parent_item.evaluate(
                """(el) => {
                  for (const node of el.querySelectorAll('span, div, button, a')) {
                    const text = (node.textContent || '').trim();
                    if (/展开|条回复|查看更多回复/.test(text)) {
                      node.click();
                      return true;
                    }
                  }
                  return false;
                }"""
            )
        )
    return False


async def _click_reply_on_comment_item(page, item) -> bool:
    """只对指定评论点一次「回复」，不切换其他用户。"""
    with contextlib.suppress(Exception):
        clicked = await item.evaluate(
            """(el) => {
              const btn = el.querySelector('.reply.icon-container');
              if (!btn) return false;
              btn.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
              btn.click();
              return true;
            }"""
        )
        if clicked:
            return True
    reply_btn = await _find_reply_btn_in_item(item)
    if reply_btn is None:
        return False
    with contextlib.suppress(Exception):
        await reply_btn.click()
        return True
    return False


async def _find_target_comment_item(
    page,
    *,
    comment_id: str,
    comment_text: str = "",
):
    """定位入库目标评论（优先 #comment-{id}，其次评论文本）。"""
    cid = str(comment_id or "").strip()
    if cid:
        for selector in (
            f".comment-item:has(#comment-{cid})",
            f".parent-comment:has(#comment-{cid})",
            f"#comment-{cid}",
        ):
            loc = page.locator(selector).first
            try:
                if not await loc.count():
                    continue
                if selector.startswith("#comment-"):
                    with contextlib.suppress(Exception):
                        await loc.scroll_into_view_if_needed(timeout=5000)
                    wrapped = page.locator(f".comment-item:has(#comment-{cid})").first
                    if await wrapped.count() and await wrapped.is_visible():
                        return wrapped
                    parent = page.locator(f".parent-comment:has(#comment-{cid})").first
                    if await parent.count() and await parent.is_visible():
                        return parent
                    if await loc.is_visible():
                        return loc
                    continue
                if await loc.is_visible():
                    return loc
            except Exception:
                continue

    text_hint = str(comment_text or "").strip()
    if not text_hint:
        return None
    async for item in _iter_comment_items(page, max_scan=24):
        try:
            inner = (await item.inner_text() or "").strip()
            if text_hint in inner:
                return item
        except Exception:
            continue
    return None


async def _scroll_until_target_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str,
    comment_text: str = "",
    parent_comment_id: str = "",
    max_rounds: int = 80,
):
    parent_id = str(parent_comment_id or "").strip()
    expanded_parent = False

    for round_idx in range(max_rounds):
        item = await _find_target_comment_item(
            page,
            comment_id=comment_id,
            comment_text=comment_text,
        )
        if item is not None:
            return item

        if parent_id and not expanded_parent:
            if await _expand_sub_comments_for_parent(
                page,
                settings,
                tenant_id=tenant_id,
                parent_comment_id=parent_id,
            ):
                expanded_parent = True
                steps_pause = True
            else:
                steps_pause = False
            item = await _find_target_comment_item(
                page,
                comment_id=comment_id,
                comment_text=comment_text,
            )
            if item is not None:
                return item
            if steps_pause:
                await _human_pause(min_s=0.8, max_s=1.2)
                continue

        if round_idx + 1 >= max_rounds:
            break
        await scroll_comment_list_in_detail(page, settings, tenant_id=tenant_id, rounds=1)
        await _human_pause(min_s=0.6, max_s=1.1)
    return None


async def _prepare_comment_panel(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    await _human_pause(min_s=0.8, max_s=1.4)
    await trigger_comment_panel(page, settings, tenant_id=tenant_id)
    if not await _wait_comment_panel_ready(page, timeout_s=10.0):
        return False
    await _human_pause(min_s=0.6, max_s=1.0)
    await scroll_comment_list_in_detail(page, settings, tenant_id=tenant_id, rounds=1)
    await _human_pause(min_s=0.5, max_s=0.9)
    return True


async def _click_reply_on_target_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str,
    comment_text: str = "",
    parent_comment_id: str = "",
) -> bool:
    """A：滚评论 + 展开 parent → 点目标评论「回复」。"""
    if not await _prepare_comment_panel(page, settings, tenant_id=tenant_id):
        return False

    item = await _scroll_until_target_comment(
        page,
        settings,
        tenant_id=tenant_id,
        comment_id=comment_id,
        comment_text=comment_text,
        parent_comment_id=parent_comment_id,
    )
    if item is None:
        return False

    await _hover_comment_item(page, item)
    await _human_pause(min_s=0.4, max_s=0.7)
    if not await _click_reply_on_comment_item(page, item):
        return False

    if not await _wait_reply_popup(page, timeout_s=12.0):
        return False

    input_loc = await _locate_reply_input_in_popup(page)
    return input_loc is not None


async def _click_reply_on_random_with_patch(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str,
    parent_comment_id: str = "",
    route_state: dict[str, Any],
) -> bool:
    """C：随机可见评论 + 点击前 patch target_comment_id，发送时 route 对齐 body。"""
    await _clear_reply_popup_mark(page)
    if not await _prepare_comment_panel(page, settings, tenant_id=tenant_id):
        return False

    item = await _pick_random_comment_item(page)
    if item is None:
        return False

    await _hover_comment_item(page, item)
    await _human_pause(min_s=0.4, max_s=0.7)
    if not await _patch_comment_item_reply_context(
        item,
        target_comment_id=comment_id,
        parent_comment_id=parent_comment_id,
    ):
        return False

    route_state["fallback_patch"] = True
    if not await _click_reply_on_comment_item(page, item):
        route_state["fallback_patch"] = False
        return False

    if not await _wait_reply_popup(page, timeout_s=12.0):
        route_state["fallback_patch"] = False
        return False

    input_loc = await _locate_reply_input_in_popup(page)
    if input_loc is None:
        route_state["fallback_patch"] = False
        return False
    return True


async def _try_open_reply_compose(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str,
    comment_text: str = "",
    parent_comment_id: str = "",
    route_state: dict[str, Any],
) -> str | None:
    """返回 reply_mode: target | fallback_patch | None。"""
    if await _click_reply_on_target_comment(
        page,
        settings,
        tenant_id=tenant_id,
        comment_id=comment_id,
        comment_text=comment_text,
        parent_comment_id=parent_comment_id,
    ):
        return "target"

    if await _click_reply_on_random_with_patch(
        page,
        settings,
        tenant_id=tenant_id,
        comment_id=comment_id,
        parent_comment_id=parent_comment_id,
        route_state=route_state,
    ):
        return "fallback_patch"

    return None


async def _locate_reply_input(page, *, timeout_s: float = 12.0):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        loc = await _locate_reply_input_in_popup(page)
        if loc is not None:
            return loc
        await asyncio.sleep(0.35)
    return None


async def _iter_comment_items(page, *, max_scan: int = 12):
    for sel in _COMMENT_ITEM_SELECTORS:
        loc = page.locator(sel)
        try:
            count = await loc.count()
        except Exception:
            continue
        for idx in range(min(count, max_scan)):
            item = loc.nth(idx)
            try:
                if await item.count() and await item.is_visible():
                    yield item
            except Exception:
                continue


async def _pick_visible_comment_item(page, *, max_scan: int = 12):
    """触达关注用：任取一条带用户链接的可见评论（不必是目标评论）。"""
    async for item in _iter_comment_items(page, max_scan=max_scan):
        try:
            has_profile = await item.evaluate(
                """(el) => Boolean(el.querySelector('a[href*="/user/profile/"]'))"""
            )
            if has_profile:
                return item
        except Exception:
            continue
    return None


async def _ensure_note_url_loaded(
    page,
    *,
    content_url: str,
    note_id: str,
) -> bool:
    url = page.url or ""
    if note_id and note_id in url and await _page_note_accessible(page):
        return True
    if not content_url:
        return False
    for attempt in range(2):
        with contextlib.suppress(Exception):
            await page.goto(content_url, wait_until="domcontentloaded", timeout=45000)
            await _human_pause(min_s=2.0, max_s=3.0)
        if await _page_note_accessible(page):
            return True
        await _human_pause(min_s=1.0, max_s=1.5)
    return await _page_note_accessible(page)


async def _type_into_reply_input(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    reply_text: str,
) -> bool:
    input_loc = await _locate_reply_input_in_popup(page)
    if input_loc is None:
        input_loc = await _locate_reply_input(page, timeout_s=6.0)
    if input_loc is None:
        return False
    await _human_pause(min_s=0.3, max_s=0.6)
    await _slow_type_reply_input(page, input_loc, reply_text)
    await _human_pause(min_s=0.5, max_s=0.9)
    return True


def _patch_comment_post_body(
    post_data: str,
    *,
    note_id: str,
    comment_id: str,
    reply_text: str,
    parent_comment_id: str = "",
) -> str:
    """fallback C：对齐 comment/post body（仅降级路径使用）。"""
    try:
        body = json.loads(post_data or "{}")
    except json.JSONDecodeError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    body["note_id"] = note_id
    body["target_comment_id"] = comment_id
    body["content"] = reply_text
    body.setdefault("at_users", [])
    parent = str(parent_comment_id or "").strip()
    if parent:
        body.setdefault("target_comment", {})
        if isinstance(body["target_comment"], dict):
            body["target_comment"].setdefault("id", parent)
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


async def _install_comment_post_route(
    page,
    route_state: dict[str, Any],
    *,
    dry_run: bool,
    note_id: str,
    comment_id: str,
    reply_text: str,
    parent_comment_id: str = "",
) -> None:
    async def _handle(route) -> None:
        if "/comment/post" not in (route.request.url or ""):
            await route.continue_()
            return
        if dry_run:
            await route.abort("blockedbyclient")
            return
        if route_state.get("fallback_patch"):
            patched = _patch_comment_post_body(
                route.request.post_data or "",
                note_id=note_id,
                comment_id=comment_id,
                reply_text=reply_text,
                parent_comment_id=parent_comment_id,
            )
            await route.continue_(post_data=patched)
            return
        await route.continue_()

    await page.route("**/*", _handle)


async def _remove_comment_post_interceptor(page) -> None:
    with contextlib.suppress(Exception):
        await page.unroute("**/*")


async def _click_send_and_wait_post(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    publish_result: dict[str, Any],
    timeout_s: float = 14.0,
) -> bool:
    from app.core.antibot import human_click
    from app.platforms.xiaohongshu.ui_helpers import dismiss_reds_alert

    async def _wait_result() -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            if publish_result.get("ok"):
                return True
            if publish_result.get("error"):
                return False
            await asyncio.sleep(0.35)
        return bool(publish_result.get("ok"))

    await dismiss_reds_alert(page)
    await _human_pause(min_s=0.4, max_s=0.8)
    with contextlib.suppress(Exception):
        await page.keyboard.press("Enter")
    if await _wait_result():
        publish_result["method"] = "enter"
        return True

    send_btn = await _locate_send_in_popup(page)
    if send_btn is None:
        publish_result["error"] = "回复弹层内 Enter 未触发发送，且未找到发送按钮"
        return False

    await dismiss_reds_alert(page)
    await _human_pause(min_s=0.5, max_s=0.9)
    await human_click(page, send_btn, settings, tenant_id=tenant_id)
    if await _wait_result():
        publish_result["method"] = "send_button"
        return True

    publish_result.setdefault("error", "Enter/发送后未捕获 comment/post 成功响应")
    return False


async def warm_publish_reply_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    comment_id: str,
    reply_text: str,
    note_id: str = "",
    comment_text: str = "",
    parent_comment_id: str = "",
    dry_run: bool = False,
    note_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A 定位目标回复 → C 随机+patch 降级 → 失败报错。"""
    text = str(reply_text or "").strip()
    target_cid = str(comment_id or "").strip()
    parent_cid = str(parent_comment_id or "").strip()
    if not target_cid:
        return {"ok": False, "error": "缺少 comment_id", "capture_method": CAPTURE_METHOD}
    if not text:
        return {"ok": False, "error": "缺少 reply_text", "capture_method": CAPTURE_METHOD}

    resolved_note = str(note_id or "").strip()
    if not resolved_note and content_url:
        with contextlib.suppress(ValueError):
            resolved_note = extract_note_id(content_url)
    if not resolved_note:
        return {"ok": False, "error": "缺少 note_id", "capture_method": CAPTURE_METHOD}

    publish_result: dict[str, Any] = {"ok": False}
    route_state: dict[str, Any] = {"fallback_patch": False}

    async def on_response(resp) -> None:
        if "/comment/post" not in (resp.url or ""):
            return
        try:
            body = await resp.json()
        except Exception:
            return
        code = body.get("code")
        success = body.get("success")
        if code == 0 or success is True:
            publish_result.update(
                {
                    "ok": True,
                    "code": code,
                    "success": success,
                    "msg": body.get("msg") or body.get("message") or "",
                    "data": body.get("data") or {},
                }
            )
        else:
            publish_result["error"] = (
                body.get("msg")
                or body.get("message")
                or body.get("error")
                or f"code={code}"
            )

    page.on("response", on_response)
    await _install_comment_post_route(
        page,
        route_state,
        dry_run=dry_run,
        note_id=resolved_note,
        comment_id=target_cid,
        reply_text=text,
        parent_comment_id=parent_cid,
    )
    steps: list[str] = []
    reply_mode: str | None = None
    capture_method = CAPTURE_METHOD
    try:
        if not await _ensure_note_url_loaded(page, content_url=content_url, note_id=resolved_note):
            return {
                "ok": False,
                "error": "笔记链接不可访问，请重新抓取更新 xsec_token",
                "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
                "steps": steps,
            }
        steps.append("stage=note_goto")
        await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
        await assert_xhs_human_ready(page, settings, tenant_id=tenant_id, stage="note")
        await _human_pause(min_s=0.8, max_s=1.2)

        reply_mode = await _try_open_reply_compose(
            page,
            settings,
            tenant_id=tenant_id,
            comment_id=target_cid,
            comment_text=str(comment_text or "").strip(),
            parent_comment_id=parent_cid,
            route_state=route_state,
        )
        if reply_mode is None:
            return {
                "ok": False,
                "error": "目标评论未出现在评论区（折叠/未加载/已删除），降级回复也未能打开弹层",
                "error_code": "comment_reply_compose_unavailable",
                "comment_id": target_cid,
                "parent_comment_id": parent_cid or None,
                "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
                "steps": steps,
                "hint": "可重新抓取该笔记评论，或确认 parent_comment_id 是否正确",
            }
        if reply_mode == "target":
            steps.append("input=target_reply_button")
            capture_method = CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD
        else:
            steps.append("input=fallback_random_reply_button")
            steps.append("patch=reply_context_before_click")
            capture_method = CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD_FALLBACK

        if not await _type_into_reply_input(
            page, settings, tenant_id=tenant_id, reply_text=text
        ):
            return {
                "ok": False,
                "error": "未能向回复弹层输入文案",
                "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
                "steps": steps,
            }
        steps.append("typed")

        would_publish = {
            "note_id": resolved_note,
            "target_comment_id": target_cid,
            "parent_comment_id": parent_cid or None,
            "reply_mode": reply_mode,
            "text_preview": text[:120],
            "submit": "native_ui_comment_post" if reply_mode == "target" else "fallback_patch_comment_post",
            "method": "Enter（失败再点弹层发送）",
        }

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "capture_method": capture_method,
                "comment_id": target_cid,
                "parent_comment_id": parent_cid or None,
                "reply_mode": reply_mode,
                "note_id": resolved_note,
                "content_url": content_url,
                "page_url": page.url,
                "steps": steps,
                "would_publish": would_publish,
                "diagnostic": "dry_run：已完成弹层 focus 与逐字输入，未按 Enter 发送",
            }

        sent_ok = await _click_send_and_wait_post(
            page,
            settings,
            tenant_id=tenant_id,
            publish_result=publish_result,
        )
        steps.append("submit=enter_or_send")
        if not sent_ok:
            return {
                "ok": False,
                "error": publish_result.get("error") or "comment_post_failed",
                "capture_method": CAPTURE_METHOD,
                "comment_id": target_cid,
                "steps": steps,
                "would_publish": would_publish,
            }
        return {
            "ok": True,
            "dry_run": False,
            "capture_method": capture_method,
            "comment_id": target_cid,
            "parent_comment_id": parent_cid or None,
            "reply_mode": reply_mode,
            "note_id": resolved_note,
            "content_url": content_url,
            "page_url": page.url,
            "steps": steps,
            "would_publish": would_publish,
            "publish": publish_result,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "capture_method": CAPTURE_METHOD_DRY if dry_run else CAPTURE_METHOD,
            "steps": steps,
        }
    finally:
        await _remove_comment_post_interceptor(page)
        await _clear_reply_popup_mark(page)
        with contextlib.suppress(Exception):
            page.remove_listener("response", on_response)
