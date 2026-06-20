"""小红书 PC 页：搜索瀑布流 → 笔记详情浮层 → 右侧评论区。"""
from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any

from app.core.antibot import human_click, human_delay
from app.core.config import Settings

# 搜索页笔记卡片（点封面/卡片，勿点作者头像；含 search_result_ai）
_NOTE_CARD_SELECTORS = (
    "section.note-item",
    '[class*="note-item"]',
    '[class*="NoteItem"]',
    '[class*="note-card"]',
    '[class*="feed-item"]',
    ".feeds-page .note-item",
    '[class*="feeds-container"] a[href*="/explore/"]',
    'a.cover[href*="/explore/"]',
    'a[href*="/explore/"][class*="cover"]',
    'a[href*="/explore/"]',
)

_NOTE_COVER_SELECTORS = (
    "a.cover",
    "a.cover.mask",
    '[class*="cover"][href*="/explore/"]',
    "img",
)

_NOTE_DETAIL_MARKERS = (
    "#detail-title",
    ".note-detail",
    ".interaction-container",
    ".comments-el",
    "#noteContainer",
    ".note-scroller",
)

_COMMENT_LIST_MARKERS = (
    ".comments-container",
    ".comment-list",
    "#comment-list",
    '[class*="comments-container"]',
    '[class*="comment-list"]',
    ".note-comment-item",
    ".parent-comment",
)

_CLOSE_DETAIL_SELECTORS = (
    ".close-circle",
    ".close-box",
    '[class*="close-circle"]',
    '[class*="close-box"]',
    ".reds-icon-close",
)

SEARCH_FEED_SCROLL_JS = """
(delta) => {
  const active = document.activeElement;
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
    active.blur();
  }
  const isContentScrollable = (el) => {
    if (!el || el === document.body || el === document.documentElement) return false;
    const r = el.getBoundingClientRect();
    const sh = el.scrollHeight || 0;
    const ch = el.clientHeight || 0;
    if (sh <= ch + 40) return false;
    if (r.height < 100) return false;
    const hasCards = el.querySelector(
      'section.note-item, [class*="note-item"], [class*="note-card"], a[href*="/explore/"]'
    );
    if (!hasCards) return false;
    if (r.top < 72 && r.height < window.innerHeight * 0.45) return false;
    return true;
  };
  const cards = [...document.querySelectorAll(
    'section.note-item, [class*="note-item"], [class*="note-card"], a[href*="/explore/"]'
  )];
  const candidates = new Set();
  for (const card of cards.slice(0, 6)) {
    let node = card;
    for (let i = 0; i < 18 && node; i++) {
      if (isContentScrollable(node)) candidates.add(node);
      node = node.parentElement;
    }
  }
  if (!candidates.size) {
    for (const sel of ['.feeds-page', '[class*="feeds-container"]', '[class*="search-layout"]', 'main']) {
      const anchor = document.querySelector(sel);
      if (!anchor) continue;
      let node = anchor;
      for (let i = 0; i < 14 && node; i++) {
        if (isContentScrollable(node)) candidates.add(node);
        node = node.parentElement;
      }
    }
  }
  let target = null;
  let bestScore = -1;
  for (const el of candidates) {
    const r = el.getBoundingClientRect();
    const overflow = (el.scrollHeight || 0) - (el.clientHeight || 0);
    const score = overflow + r.height + (r.top > 140 ? 800 : 0);
    if (score > bestScore) {
      bestScore = score;
      target = el;
    }
  }
  if (!target) return false;
  const before = target.scrollTop || 0;
  const step = Math.max(28, Math.min(200, Number(delta) || 680));
  const maxTop = Math.max(0, (target.scrollHeight || 0) - (target.clientHeight || 0));
  target.scrollTop = Math.min(before + step, maxTop);
  return target.scrollTop > before;
}
"""

_SEARCH_WHEEL_TARGETS = (
    "section.note-item",
    '[class*="note-item"]',
    '[class*="note-card"]',
    ".feeds-page",
    '[class*="feeds-container"]',
    '[class*="search-layout"]',
    '[class*="search-result"]',
    '[class*="search-feed"]',
)

COMMENT_LIST_SCROLL_JS = """
() => {
  const markers = [
    '.comments-container',
    '.comment-list',
    '#comment-list',
    '[class*="comments-container"]',
    '[class*="comment-list"]',
    '.list-container',
    '.interaction-container',
    '.note-scroller',
  ];
  const anchors = [];
  for (const sel of markers) {
    document.querySelectorAll(sel).forEach((el) => anchors.push(el));
  }
  const commentItems = [...document.querySelectorAll('.comment-item, [class*="comment-item"], .parent-comment')];
  if (commentItems.length) anchors.push(commentItems[commentItems.length - 1]);

  const pickScrollParent = (anchor) => {
    let node = anchor;
    for (let i = 0; i < 14 && node; i++) {
      const sh = node.scrollHeight || 0;
      const ch = node.clientHeight || 0;
      if (sh > ch + 30) return node;
      node = node.parentElement;
    }
    return null;
  };
  for (const anchor of anchors) {
    const target = pickScrollParent(anchor);
    if (!target) continue;
    const before = target.scrollTop || 0;
    target.scrollTop = Math.min(before + 480, target.scrollHeight);
    if (target.scrollTop > before) return true;
  }
  return false;
}
"""

FIND_NOTE_HREF_JS = """
(noteId) => {
  const links = [...document.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/item/"]')];
  let fallback = '';
  for (const a of links) {
    const href = a.href || a.getAttribute('href') || '';
    if (!href.includes(noteId)) continue;
    if (href.includes('xsec_token')) return href;
    if (!fallback) fallback = href;
  }
  return fallback;
}
"""

COLLECT_VISIBLE_NOTE_IDS_JS = """
() => {
  const out = [];
  const seen = new Set();
  const links = document.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/item/"]');
  for (const a of links) {
    const href = a.getAttribute('href') || a.href || '';
    const m = href.match(/(?:\\/explore\\/|\\/discovery\\/item\\/)([0-9a-fA-F]{16,32})/);
    if (!m || seen.has(m[1])) continue;
    const r = a.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) continue;
    if (r.bottom < 0 || r.top > window.innerHeight * 1.35) continue;
    seen.add(m[1]);
    out.push(m[1]);
  }
  return out;
}
"""

CLICK_NOTE_BY_ID_JS = """
(noteId) => {
  const isVisible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 24 && r.height > 24 && r.bottom > 0 && r.top < window.innerHeight * 1.35;
  };
  const clickEl = (el) => {
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    const rect = el.getBoundingClientRect();
    const x = rect.left + rect.width * 0.5;
    const y = rect.top + rect.height * 0.5;
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  };
  const links = [...document.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/item/"]')];
  for (const a of links) {
    const href = a.href || a.getAttribute('href') || '';
    if (!href.includes(noteId) || !isVisible(a)) continue;
    clickEl(a);
    return { ok: true, href };
  }
  const attrs = ['data-note-id', 'data-id', 'data-noteid', 'note-id'];
  for (const name of attrs) {
    const hit = document.querySelector(`[${name}="${noteId}"]`);
    if (!hit) continue;
    const card = hit.closest('section, [class*="note"], [class*="card"], a') || hit;
    if (isVisible(card)) {
      clickEl(card);
      return { ok: true, href: '' };
    }
  }
  return { ok: false, href: '' };
}
"""

DISMISS_AI_SUMMARY_JS = """
() => {
  const isSummary = (el) => {
    const t = (el.textContent || '').trim();
    return t.includes('ai总结') || t.includes('篇笔记生成') || t.includes('AI总结');
  };
  const nodes = [...document.querySelectorAll('div, span, p, section')];
  for (const el of nodes) {
    if (!isSummary(el)) continue;
    let root = el;
    for (let i = 0; i < 10 && root; i++) {
      const close = root.querySelector(
        '.reds-icon-close, [class*="close-icon"], [class*="Close"], button[aria-label*="关闭"], button[aria-label*="close"]'
      );
      if (close) {
        close.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        return true;
      }
      root = root.parentElement;
    }
  }
  return false;
}
"""

NOTE_DETAIL_OPEN_JS = """
() => {
  const href = location.href || '';
  const path = (location.pathname || '').replace(/\\/$/, '') || '/';
  const onExploreHome = path === '/explore' && !href.includes('search_result');
  const onSearch = href.includes('search_result');
  const noteInUrl = /\\/explore\\/[0-9a-fA-F]{16,32}/.test(href)
    || /\\/discovery\\/item\\/[0-9a-fA-F]{16,32}/.test(href);

  const isVisible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 8 && r.height > 8 && r.bottom > 0 && r.top < window.innerHeight;
  };

  const closeBtn = document.querySelector(
    '.close-circle, .close-box, [class*="close-circle"], [class*="close-box"]'
  );
  const closeVisible = isVisible(closeBtn);
  const detailTitle = document.querySelector('#detail-title');
  const commentInput = document.querySelector(
    'div.content-input [contenteditable="true"], textarea[placeholder*="说点什么"], [placeholder*="说点什么"]'
  );
  const commentItems = [...document.querySelectorAll(
    '.note-comment-item, .parent-comment, #comment-list > div'
  )].filter(isVisible);
  const interaction = document.querySelector('.interaction-container, .comments-el');
  const hasDetailBody = isVisible(detailTitle) || isVisible(commentInput)
    || commentItems.length > 0 || isVisible(interaction);

  if (onExploreHome) {
    // 探索首页瀑布流不是笔记浮层；仅搜索页点开的 modal 才算
    return false;
  }
  if (onSearch) {
    // AI 总结侧栏也有 X，不能仅凭关闭按钮判断；需笔记浮层特有元素
    const modalClose = document.querySelector('.close-circle, .reds-icon-close');
    const hasNoteModal = isVisible(detailTitle) || commentItems.length > 0;
    return isVisible(modalClose) && hasNoteModal;
  }
  if (noteInUrl) {
    return hasDetailBody;
  }
  return false;
}
"""

NOTE_DETAIL_HAS_ID_JS = """
(noteId) => {
  if (!noteId) return true;
  if (location.href.includes(noteId)) return true;
  const markers = document.querySelectorAll(
    '#detail-title, .note-detail, [class*="note-detail"], #noteContainer, [class*="note-container"], .interaction-container'
  );
  let scope = document.body;
  for (const m of markers) {
    const r = m.getBoundingClientRect();
    if (r.width > 40 && r.height > 40) {
      scope = m.closest('[class*="note"], [class*="detail"], [role="dialog"]') || m;
      break;
    }
  }
  const links = scope.querySelectorAll(`a[href*="${noteId}"]`);
  for (const a of links) {
    const r = a.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return true;
  }
  const html = scope.innerHTML || '';
  return html.includes(noteId);
}
"""


async def find_note_href_on_search(page, note_id: str) -> str:
    if not note_id:
        return ""
    try:
        href = await page.evaluate(FIND_NOTE_HREF_JS, note_id)
        return str(href or "").strip()
    except Exception:
        return ""


async def _note_detail_matches_id(page, note_id: str) -> bool:
    if not note_id:
        return True
    try:
        return bool(await page.evaluate(NOTE_DETAIL_HAS_ID_JS, note_id))
    except Exception:
        return note_id in (page.url or "")


async def _wait_search_note_cards(page, *, rounds: int = 8, delay_ms: int = 900) -> bool:
    for _ in range(max(1, rounds)):
        if await page_has_search_note_cards(page):
            return True
        await page.wait_for_timeout(delay_ms)
    return await page_has_search_note_cards(page)


async def _click_note_by_id_js(
    page,
    note_id: str,
    settings: Settings,
    *,
    tenant_id: str,
) -> str:
    if not note_id:
        return ""
    try:
        result = await page.evaluate(CLICK_NOTE_BY_ID_JS, note_id)
    except Exception:
        return ""
    if not isinstance(result, dict) or not result.get("ok"):
        return ""
    await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    return str(result.get("href") or "").strip()


async def _page_note_access_ok(page) -> bool:
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    if "页面不见了" in title or "/404" in (page.url or ""):
        return False
    return await is_note_detail_open(page)


async def open_note_by_resolved_url(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    open_url: str,
) -> bool:
    url = str(open_url or "").strip()
    if not url:
        return False
    await page.goto(url, wait_until="domcontentloaded", timeout=120000)
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    if not await _page_note_access_ok(page):
        return False
    await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
    return True


def _on_explore_home_page(url: str | None) -> bool:
    """探索页信息流首页（非笔记详情、非搜索页）。"""
    raw = (url or "").split("?")[0].rstrip("/")
    if "search_result" in (url or ""):
        return False
    return raw.endswith("xiaohongshu.com/explore") or raw.endswith("www.xiaohongshu.com/explore")


def _on_search_results_page(url: str | None) -> bool:
    return "search_result" in (url or "")


def _on_note_explore_page(url: str | None) -> bool:
    u = url or ""
    return "/explore/" in u or "/discovery/item/" in u


async def detect_page_scene(page) -> str:
    from app.services.ui_flow.platforms.xiaohongshu.filter_ui import is_filter_panel_open

    if await is_filter_panel_open(page):
        return "search_filter_panel"
    url = page.url or ""
    if _on_explore_home_page(url):
        return "explore_home"
    if await is_note_detail_open(page):
        if _on_search_results_page(url):
            return "search_note_modal"
        if _on_note_explore_page(url):
            return "note_full_page"
        return "note_detail"
    if _on_search_results_page(url):
        return "search_results"
    if "xiaohongshu.com/explore" in url and "search_result" not in url:
        return "explore_home"
    return "unknown"


async def is_note_detail_open(page) -> bool:
    try:
        open_detail = await page.evaluate(NOTE_DETAIL_OPEN_JS)
        if isinstance(open_detail, bool):
            return open_detail
    except Exception:
        pass

    url = page.url or ""
    if _on_explore_home_page(url):
        return False

    for selector in _NOTE_DETAIL_MARKERS:
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                if _on_search_results_page(url):
                    close = page.locator(
                        ".close-circle, .close-box, [class*='close-circle']"
                    ).first
                    if not await close.count() or not await close.is_visible():
                        continue
                return True
        except Exception:
            continue
    return False


async def page_has_search_note_cards(page) -> bool:
    if not _on_search_results_page(page.url):
        return False
    for selector in _NOTE_CARD_SELECTORS:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    try:
        ids = await page.evaluate(COLLECT_VISIBLE_NOTE_IDS_JS)
        return bool(ids)
    except Exception:
        return False


async def dismiss_page_overlays(page, settings: Settings, *, tenant_id: str) -> None:
    from app.platforms.xiaohongshu.ui_helpers import dismiss_login_overlay

    with contextlib.suppress(Exception):
        await dismiss_login_overlay(page)
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")
        await human_delay(page, settings, tenant_id=tenant_id, profile="action")


async def close_note_detail(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    for selector in _CLOSE_DETAIL_SELECTORS:
        loc = page.locator(selector).first
        try:
            if await loc.count() and await loc.is_visible():
                await human_click(page, loc, settings, tenant_id=tenant_id)
                await human_delay(page, settings, tenant_id=tenant_id, profile="action")
                if not await is_note_detail_open(page):
                    return True
        except Exception:
            continue
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")
        await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    return not await is_note_detail_open(page)


async def back_to_search_list(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    search_url: str = "",
) -> bool:
    if await is_note_detail_open(page):
        await close_note_detail(page, settings, tenant_id=tenant_id)
    if await page_has_search_note_cards(page):
        return True
    target = str(search_url or "").strip()
    if target and "search_result" in target:
        with contextlib.suppress(Exception):
            await page.goto(target, wait_until="domcontentloaded", timeout=45000)
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    return await page_has_search_note_cards(page)


async def _search_results_wheel_point(page) -> tuple[float, float] | None:
    """wheel 落点：瀑布流内容区，避开顶栏搜索/筛选。"""
    for selector in _SEARCH_WHEEL_TARGETS:
        loc = page.locator(selector).first
        try:
            if not await loc.count() or not await loc.is_visible():
                continue
            box = await loc.bounding_box()
            if not box or box["y"] < 160:
                continue
            x = box["x"] + box["width"] * 0.38
            y = box["y"] + box["height"] * 0.55
            return x, y
        except Exception:
            continue
    vp = page.viewport_size or {"width": 1440, "height": 900}
    return float(vp["width"] * 0.38), float(vp["height"] * 0.58)


def _human_scroll_total(delta_y: int | None) -> int:
    if delta_y is not None:
        return max(180, min(int(delta_y), 520))
    return random.randint(280, 460)


async def _human_wheel_segments(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    total: int,
    point: tuple[float, float] | None = None,
) -> None:
    if point is not None:
        x, y = point
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.15, 0.45))

    segments = random.randint(3, 6)
    remaining = total
    for index in range(segments):
        if index == segments - 1:
            chunk = remaining
        else:
            chunk = max(35, int(remaining * random.uniform(0.18, 0.38)))
            remaining -= chunk
        sub_steps = random.randint(2, 4)
        step_size = max(12, chunk // sub_steps)
        for _ in range(sub_steps):
            jitter = random.randint(-6, 6)
            await page.mouse.wheel(0, step_size + jitter)
            await asyncio.sleep(random.uniform(0.06, 0.22))
        await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
    if random.random() < 0.2:
        await page.mouse.wheel(0, -random.randint(20, 70))
        await asyncio.sleep(random.uniform(0.25, 0.55))


async def _human_dom_scroll_steps(page, total: int) -> bool:
    steps = random.randint(4, 8)
    per_step = max(32, total // steps)
    scrolled_any = False
    for _ in range(steps):
        step = per_step + random.randint(-12, 12)
        with contextlib.suppress(Exception):
            if await page.evaluate(SEARCH_FEED_SCROLL_JS, step):
                scrolled_any = True
        await asyncio.sleep(random.uniform(0.14, 0.38))
    return scrolled_any


async def scroll_search_results_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    delta_y: int | None = None,
) -> bool:
    """在搜索结果瀑布流内容区滚动（先释放顶栏焦点，再在列表区域 wheel/DOM 滚）。"""
    from app.services.ui_flow.platforms.xiaohongshu.filter_ui import (
        is_filter_panel_open,
        release_searchbar_focus,
    )

    if await is_filter_panel_open(page):
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        await asyncio.sleep(0.35)

    total = _human_scroll_total(delta_y)
    await release_searchbar_focus(page)
    await asyncio.sleep(random.uniform(0.25, 0.65))

    point = await _search_results_wheel_point(page)
    if await _human_dom_scroll_steps(page, total):
        await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
        return True

    await _human_wheel_segments(page, settings, tenant_id=tenant_id, total=total, point=point)
    return point is not None


async def scroll_search_feed(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 1,
) -> None:
    for _ in range(max(1, rounds)):
        await scroll_search_results_page(page, settings, tenant_id=tenant_id)


async def scroll_comment_list_in_detail(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 1,
) -> bool:
    if not await is_note_detail_open(page):
        return False
    scrolled = False
    for _ in range(max(1, rounds)):
        with contextlib.suppress(Exception):
            if await page.evaluate(COMMENT_LIST_SCROLL_JS):
                scrolled = True
        await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
        for selector in _COMMENT_LIST_MARKERS:
            loc = page.locator(selector).last
            try:
                if not await loc.count() or not await loc.is_visible():
                    continue
                box = await loc.bounding_box()
                if not box:
                    continue
                x = box["x"] + box["width"] * 0.55
                y = box["y"] + box["height"] * 0.55
                await page.mouse.move(x, y)
                await page.mouse.wheel(0, 420)
                scrolled = True
                break
            except Exception:
                continue
    return scrolled


async def activate_comments_on_detail(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    if await is_note_detail_open(page):
        for selector in (
            'span:has-text("条评论")',
            'div:has-text("条评论")',
            'span:has-text("评论")',
            ".chat-wrapper",
            ".comments-el",
        ):
            loc = page.locator(selector).first
            try:
                if await loc.count() and await loc.is_visible():
                    await human_click(page, loc, settings, tenant_id=tenant_id)
                    await human_delay(page, settings, tenant_id=tenant_id, profile="action")
                    return True
            except Exception:
                continue
        return True
    return False


async def _find_note_card_at_index(page, index: int):
    for selector in _NOTE_CARD_SELECTORS:
        cards = page.locator(selector)
        try:
            count = await cards.count()
        except Exception:
            continue
        if count > index:
            return cards.nth(index)
    return None


async def _click_note_cover(
    page,
    card,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    for selector in _NOTE_COVER_SELECTORS:
        target = card.locator(selector).first
        try:
            if await target.count() and await target.is_visible():
                await target.scroll_into_view_if_needed(timeout=5000)
                await human_click(page, target, settings, tenant_id=tenant_id)
                return True
        except Exception:
            continue
    try:
        await card.scroll_into_view_if_needed(timeout=5000)
        await human_click(page, card, settings, tenant_id=tenant_id)
        return True
    except Exception:
        return False


async def _click_note_by_id_from_search(
    page,
    note_id: str,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    if not note_id:
        return False

    clicked_href = await _click_note_by_id_js(page, note_id, settings, tenant_id=tenant_id)
    if clicked_href:
        return True

    selectors = (
        f'section.note-item a[href*="{note_id}"]',
        f'[class*="note-item"] a[href*="{note_id}"]',
        f'a.cover[href*="{note_id}"]',
        f'a[href*="/explore/{note_id}"]',
    )
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if not await loc.count():
                continue
            parent = loc.locator(
                "xpath=ancestor::*[contains(@class,'note-item') or contains(@class,'note-card')][1]"
            ).first
            click_target = parent if await parent.count() else loc
            await click_target.scroll_into_view_if_needed(timeout=5000)
            cover = click_target.locator("a.cover, a[href*='/explore/']").first
            if await cover.count():
                await human_click(page, cover, settings, tenant_id=tenant_id)
            else:
                await human_click(page, click_target, settings, tenant_id=tenant_id)
            return True
        except Exception:
            continue
    return False


async def ensure_search_cards_for_index(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    index: int,
    max_scroll_rounds: int = 8,
) -> bool:
    for _ in range(max_scroll_rounds):
        card = await _find_note_card_at_index(page, index)
        if card is not None:
            try:
                if await card.count():
                    return True
            except Exception:
                pass
        try:
            ids = await page.evaluate(COLLECT_VISIBLE_NOTE_IDS_JS)
            if isinstance(ids, list) and len(ids) > index:
                return True
        except Exception:
            pass
        await scroll_search_feed(page, settings, tenant_id=tenant_id, rounds=1)
    return False


async def click_search_note_at_index(
    ctx,
    index: int,
    *,
    note_id: str = "",
    fallback_url: str = "",
) -> dict[str, Any]:
    """从搜索瀑布流点第 index 个笔记封面进入详情（优先 UI，失败再 goto）。"""
    page = ctx.page
    settings = ctx.settings
    tenant_id = ctx.tenant_id
    search_url = str(ctx.state.get("search_url") or page.url or "")

    await back_to_search_list(page, settings, tenant_id=tenant_id, search_url=search_url)
    await dismiss_page_overlays(page, settings, tenant_id=tenant_id)

    if not await page_has_search_note_cards(page) and fallback_url:
        with contextlib.suppress(Exception):
            await page.goto(fallback_url, wait_until="domcontentloaded", timeout=120000)
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
        if await is_note_detail_open(page):
            return {"ok": True, "method": "goto_fallback", "detail_open": True}

    await ensure_search_cards_for_index(
        page, settings, tenant_id=tenant_id, index=index
    )

    note_href = ""
    if note_id:
        note_href = await find_note_href_on_search(page, note_id)

    clicked = False
    method = ""
    if note_id and await _click_note_by_id_from_search(
        page, note_id, settings, tenant_id=tenant_id
    ):
        clicked = True
        method = "click_by_note_id"
    if not clicked:
        card = await _find_note_card_at_index(page, index)
        if card is not None:
            clicked = await _click_note_cover(page, card, settings, tenant_id=tenant_id)
            if clicked:
                method = "click_card_index"

    if not clicked and fallback_url:
        if await open_note_by_resolved_url(
            page, settings, tenant_id=tenant_id, open_url=fallback_url
        ):
            clicked = True
            method = "goto_fallback"

    if not clicked:
        return {"ok": False, "method": method or "none", "detail_open": False, "note_href": note_href}

    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    detail_open = await _page_note_access_ok(page)
    if detail_open:
        await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
    if not note_href:
        if note_id and note_id in (page.url or ""):
            note_href = page.url
        else:
            note_href = await find_note_href_on_search(page, note_id) if note_id else ""
    return {
        "ok": detail_open,
        "method": method,
        "detail_open": detail_open,
        "note_href": note_href or fallback_url or page.url,
    }


async def _note_page_accessible(page) -> bool:
    title = ""
    with contextlib.suppress(Exception):
        title = await page.title()
    url = page.url or ""
    if "页面不见了" in title or "/404" in url:
        return False
    return True


async def dismiss_ai_search_side_panel(page, settings: Settings, *, tenant_id: str) -> bool:
    """关闭 search_result_ai 右侧 AI 总结侧栏，避免占屏/误判。"""
    dismissed = False
    with contextlib.suppress(Exception):
        dismissed = bool(await page.evaluate(DISMISS_AI_SUMMARY_JS))
    if dismissed:
        await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    return dismissed


async def _scroll_search_until_note_visible(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    note_id: str,
    max_rounds: int = 3,
) -> bool:
    for _ in range(max(1, max_rounds)):
        try:
            ids = await page.evaluate(COLLECT_VISIBLE_NOTE_IDS_JS)
            if isinstance(ids, list) and note_id in ids:
                return True
        except Exception:
            pass
        await scroll_search_results_page(page, settings, tenant_id=tenant_id)
    return False


async def _click_note_on_search_list(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    note_id: str,
    max_attempts: int = 4,
) -> bool:
    """搜索列表点笔记：先关 AI 侧栏 → 尝试点击 → 必要时少量滚动，禁止长距离扫屏。"""
    await dismiss_ai_search_side_panel(page, settings, tenant_id=tenant_id)

    for attempt in range(max(1, max_attempts)):
        if note_id:
            try:
                ids = await page.evaluate(COLLECT_VISIBLE_NOTE_IDS_JS)
                if isinstance(ids, list) and note_id in ids:
                    if await _click_note_by_id_from_search(
                        page, note_id, settings, tenant_id=tenant_id
                    ):
                        return True
            except Exception:
                pass
            if await _click_note_by_id_from_search(
                page, note_id, settings, tenant_id=tenant_id
            ):
                return True

        if attempt + 1 < max_attempts:
            await scroll_search_results_page(page, settings, tenant_id=tenant_id)
            await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
    return False


async def open_note_for_ui_action(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    content_url: str,
    note_id: str = "",
    note_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """触达/回复：优先用入库笔记链接直达，否则搜索列表点封面。"""
    from app.platforms.xiaohongshu.utils import extract_note_access_params, resolve_note_open_url

    await dismiss_page_overlays(page, settings, tenant_id=tenant_id)
    target_id = str(note_id or "").strip()
    if not target_id and content_url:
        with contextlib.suppress(ValueError):
            from app.platforms.xiaohongshu.utils import extract_note_id

            target_id = extract_note_id(content_url)

    if (
        target_id
        and not _on_explore_home_page(page.url)
        and await is_note_detail_open(page)
        and await _page_note_access_ok(page)
    ):
        if await _note_detail_matches_id(page, target_id):
            await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
            return {"ok": True, "method": "already_open"}

    open_url = resolve_note_open_url(
        target_id,
        content_url=content_url,
        note_meta=note_meta,
    )
    search_url = str((note_meta or {}).get("search_url") or "").strip()
    if search_url and "search_result" in search_url:
        if not await page_has_search_note_cards(page):
            with contextlib.suppress(Exception):
                await page.goto(search_url, wait_until="domcontentloaded", timeout=120000)
                await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
            await _wait_search_note_cards(page)
        await dismiss_ai_search_side_panel(page, settings, tenant_id=tenant_id)

    if target_id and await page_has_search_note_cards(page):
        if await _click_note_on_search_list(
            page, settings, tenant_id=tenant_id, note_id=target_id
        ):
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
            if await _page_note_access_ok(page) and await _note_detail_matches_id(page, target_id):
                await activate_comments_on_detail(page, settings, tenant_id=tenant_id)
                clicked_href = await find_note_href_on_search(page, target_id)
                if target_id in (page.url or ""):
                    clicked_href = page.url
                return {
                    "ok": True,
                    "method": "search_click",
                    "open_url": clicked_href or open_url,
                }

    if open_url and extract_note_access_params(open_url).get("xsec_token"):
        if await open_note_by_resolved_url(page, settings, tenant_id=tenant_id, open_url=open_url):
            return {"ok": True, "method": "stored_url", "open_url": open_url}

    return {"ok": False, "method": "none", "open_url": open_url}
