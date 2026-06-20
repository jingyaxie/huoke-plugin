from __future__ import annotations

import asyncio
import contextlib
import random
import re

from app.core.antibot import human_click, human_delay
from app.services.ui_flow.platforms.douyin.feed_ui import (
    close_feed_detail_on_page,
    feed_overlay_visible,
    is_feed_detail_open,
    wait_feed_detail,
)
from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

_PROFILE_VIDEO_ITEM_SELECTORS = (
    '[data-e2e="user-post-item"]',
    'ul[data-e2e="user-post-item-list"] > li',
    'div[data-e2e="user-post-item-list"] li',
)

_COLLECT_PROFILE_CARDS_JS = """
(limit) => {
  const cards = [];
  const seen = new Set();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 40 && r.height >= 40 && r.bottom > 0 && r.top < window.innerHeight + 80;
  };
  const extractAweme = (el) => {
    const link =
      el.closest('a[href*="/video/"]') ||
      el.querySelector('a[href*="/video/"]') ||
      (el.tagName === 'A' ? el : null);
    if (link) {
      const m = (link.getAttribute('href') || '').match(/\\/video\\/(\\d+)/);
      if (m) return m[1];
    }
    const href = el.getAttribute('href') || '';
    const m2 = href.match(/\\/video\\/(\\d+)/);
    return m2 ? m2[1] : '';
  };
  const pushCard = (el, aweme) => {
    if (!aweme || seen.has(aweme)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) return;
    seen.add(aweme);
    cards.push({
      aweme,
      top: r.top,
      left: r.left,
      width: r.width,
      height: r.height,
    });
  };
  const itemSelectors = [
    '[data-e2e="user-post-item"]',
    'ul[data-e2e="user-post-item-list"] > li',
    'div[data-e2e="user-post-item-list"] li',
    '[class*="UserPost"] li',
    '[class*="user-post"] li',
  ];
  for (const sel of itemSelectors) {
    for (const el of document.querySelectorAll(sel)) {
      const aweme = extractAweme(el);
      if (aweme && visible(el)) pushCard(el, aweme);
      if (cards.length >= limit) break;
    }
    if (cards.length >= limit) break;
  }
  if (cards.length < limit) {
    for (const a of document.querySelectorAll('a[href*="/video/"]')) {
      const m = (a.getAttribute('href') || '').match(/\\/video\\/(\\d+)/);
      if (m && visible(a)) pushCard(a, m[1]);
      if (cards.length >= limit) break;
    }
  }
  cards.sort((a, b) => a.top - b.top || a.left - b.left);
  return cards.slice(0, limit);
}
"""


def on_profile_url(url: str) -> bool:
    return "/user/" in (url or "").lower()


async def profile_list_visible(page) -> bool:
    """仍在账号主页作品列表（无 Feed 浮层、非独立视频页）。"""
    url = page.url or ""
    if not on_profile_url(url):
        return False
    if re.search(r"/video/\d+", url.lower()):
        return False
    if await feed_overlay_visible(page):
        return False
    return await count_profile_video_items(page) > 0


async def count_profile_video_items(page) -> int:
    cards = await collect_profile_video_cards(page, limit=200)
    return len(cards)


async def collect_profile_video_cards(page, *, limit: int = 50) -> list[dict]:
    try:
        raw = await page.evaluate(_COLLECT_PROFILE_CARDS_JS, limit)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict) and row.get("aweme")]


async def scroll_profile_videos_page(page, settings, *, tenant_id: str) -> None:
    await page.evaluate("() => { window.scrollBy(0, Math.min(window.innerHeight, 720)); }")
    await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")


async def back_to_profile_list(ctx: DouyinUiSession) -> bool:
    """从 Feed 回到主页作品列表，准备点下一个视频。"""
    page = ctx.page
    settings = ctx.settings
    tenant_id = ctx.tenant_id

    if await profile_list_visible(page):
        ctx.state["feed_mode"] = False
        return True

    if on_profile_url(page.url or "") and not await feed_overlay_visible(page):
        ctx.state["feed_mode"] = False
        return True

    if ctx.state.get("feed_mode") or await is_feed_detail_open(page):
        for _ in range(2):
            with contextlib.suppress(Exception):
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.18)
        await close_feed_detail_on_page(page, settings, tenant_id=tenant_id)
        ctx.state["feed_mode"] = False

    if await profile_list_visible(page):
        return True

    profile_url = str(ctx.state.get("profile_url") or "")
    if profile_url:
        need_goto = (
            not on_profile_url(page.url or "")
            or bool(re.search(r"/video/\d+", page.url or ""))
            or await is_feed_detail_open(page)
        )
        if need_goto:
            try:
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
                await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
            except Exception:
                pass
            for _ in range(10):
                if await profile_list_visible(page):
                    return True
                await asyncio.sleep(0.12)

    return await profile_list_visible(page)


async def ensure_profile_item_index(ctx: DouyinUiSession, index: int) -> bool:
    """主页作品不足时滚动加载，直到 index 可点。"""
    page = ctx.page
    cards = await collect_profile_video_cards(page, limit=index + 1)
    if len(cards) > index:
        return True
    if not await profile_list_visible(page):
        return len(cards) > index
    for _ in range(4):
        cards = await collect_profile_video_cards(page, limit=index + 1)
        if len(cards) > index:
            return True
        await scroll_profile_videos_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        await asyncio.sleep(random.uniform(0.5, 1.0))
    cards = await collect_profile_video_cards(page, limit=index + 1)
    return len(cards) > index


async def click_profile_video_at_index(
    ctx: DouyinUiSession,
    index: int,
    *,
    aweme_id: str = "",
) -> tuple[bool, str]:
    """点击主页作品列表第 N 个视频（坐标点击，模拟人类）。"""
    page = ctx.page
    hint = str(aweme_id or "").strip()
    if not hint:
        stored = list(ctx.state.get("profile_aweme_ids") or [])
        if len(stored) > index:
            hint = str(stored[index] or "")
    if not hint:
        urls = list(ctx.state.get("manual_video_urls") or [])
        if len(urls) > index:
            from app.platforms.douyin.js_constants import _extract_aweme_id

            try:
                hint = _extract_aweme_id(urls[index])
            except ValueError:
                hint = urls[index].rstrip("/").split("/")[-1]

    if not await ensure_profile_item_index(ctx, index):
        return False, f"主页列表第 {index + 1} 项不可用（滚动后仍不足）"

    cards = await collect_profile_video_cards(page, limit=max(index + 1, 50))
    target_card = None
    if hint:
        for card in cards:
            if str(card.get("aweme") or "") == hint:
                target_card = card
                break
    if target_card is None and len(cards) > index:
        target_card = cards[index]
    if not target_card:
        return False, f"profile_no_card index={index} aweme={hint[:12] if hint else 'none'}"

    x = float(target_card.get("left") or 0) + float(target_card.get("width") or 0) / 2
    y = float(target_card.get("top") or 0) + float(target_card.get("height") or 0) / 2
    await page.mouse.move(x, y)
    await human_delay(page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
    await page.mouse.click(x, y)

    if await wait_feed_detail(page, max_sec=5.0):
        ctx.state["feed_mode"] = True
        aw = str(target_card.get("aweme") or hint)
        return True, f"profile_click index={index} aweme={aw[:16]}"

    if hint:
        link = page.locator(f'a[href*="/video/{hint}"]').first
        try:
            if await link.count():
                await link.scroll_into_view_if_needed(timeout=3000)
                parent = link.locator(
                    "xpath=ancestor::li[1] | ancestor::div[contains(@data-e2e,'user-post')][1]"
                ).first
                click_target = parent if await parent.count() else link
                await human_click(page, click_target, ctx.settings, tenant_id=ctx.tenant_id)
                if await wait_feed_detail(page, max_sec=5.0):
                    ctx.state["feed_mode"] = True
                    return True, f"profile_link_click aweme={hint[:16]}"
        except Exception as exc:
            return False, f"profile_click_fail index={index} {exc}"

    return False, f"profile_click_no_feed index={index}"
