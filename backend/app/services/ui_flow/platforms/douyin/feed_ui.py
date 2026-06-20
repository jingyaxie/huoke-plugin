from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any

from app.core.antibot import human_click, human_delay
from app.core.config import Settings
from app.platforms.douyin.js_constants import _normalize_comment

# Feed 流详情：左侧视频 + 右侧评论侧栏（见产品截图）
_COMMENT_TAB_SELECTORS = (
    '[data-e2e="detail-tab-comment"]',
    'div[role="tab"]:has-text("评论")',
    'span:text-is("评论")',
    'text=评论',
)
_COMMENT_SIDEBAR_MARKERS = (
    'text=全部评论',
    '[data-e2e="comment-item"]',
    '[class*="CommentItem"]',
)
_CLOSE_FEED_SELECTORS = (
    '[data-e2e="close-icon"]',
    '[aria-label="关闭"]',
    'button[aria-label="关闭"]',
    '[class*="close-btn"]',
)
_FEED_MODAL_COMMENT_ROOT = '[data-e2e="feed-active-video"]'
# 仅精确评论入口，禁止宽泛 interaction/svg（易误点红心点赞）
_COMMENT_ICON_SELECTORS = (
    '[data-e2e="feed-comment-icon"]',
    '[data-e2e="comment-icon"]',
    f'{_FEED_MODAL_COMMENT_ROOT} [data-e2e="feed-comment-icon"]',
    '[class*="comment"] [data-e2e="feed-comment-icon"]',
)

_CLICK_COMMENT_ICON_JS = """
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 10 && r.height >= 10 && r.top >= 0 && r.bottom <= window.innerHeight + 4;
  };
  const clickEl = (el) => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    return true;
  };
  for (const sel of [
    '[data-e2e="feed-comment-icon"]',
    '[data-e2e="comment-icon"]',
    '[data-e2e="detail-tab-comment"]',
  ]) {
    for (const el of document.querySelectorAll(sel)) {
      if (visible(el)) {
        clickEl(el);
        return sel;
      }
    }
  }
  for (const el of document.querySelectorAll('div[role="tab"], span, div, button')) {
    const t = (el.textContent || '').replace(/\\s+/g, '');
    if (t !== '评论' && !t.startsWith('评论(')) continue;
    if (!visible(el)) continue;
    clickEl(el);
    return 'tab:评论';
  }
  return '';
}
"""
_COMMENT_WHEEL_TARGETS = (
    f'{_FEED_MODAL_COMMENT_ROOT} [data-e2e="comment-item"]',
    '[data-e2e="comment-item"]',
    'text=全部评论',
)

COMMENT_SIDEBAR_SCROLL_JS = """
() => {
  const items = [...document.querySelectorAll('[data-e2e="comment-item"]')];
  const anchors = [];
  if (items.length) anchors.push(items[items.length - 1]);
  const header = [...document.querySelectorAll('*')].find(el => {
    const t = (el.textContent || '').trim();
    return t.startsWith('全部评论');
  });
  if (header) anchors.push(header);
  const feed = document.querySelector('[data-e2e="feed-active-video"]');
  if (feed) anchors.push(feed);

  for (const anchor of anchors) {
    let node = anchor;
    for (let i = 0; i < 12 && node; i++) {
      const sh = node.scrollHeight || 0;
      const ch = node.clientHeight || 0;
      if (sh > ch + 30) {
        const before = node.scrollTop || 0;
        node.scrollTop = Math.min(before + 520, sh);
        return node.scrollTop > before || sh > ch + 120;
      }
      node = node.parentElement;
    }
  }
  return false;
}
"""


_FEED_OVERLAY_SELECTORS = (
    _FEED_MODAL_COMMENT_ROOT,
    '[data-e2e="feed-comment-icon"]',
    '[data-e2e="comment-icon"]',
    '[data-e2e="detail-tab-comment"]',
)
_SEARCH_LIST_POSTER_SELECTORS = (
    '[class*="discover-video-card"]',
    'div.search-result-card',
    '[data-e2e="search-card-video"]',
    '[class*="search-result-card"]',
)


async def _locator_visible(page, selector: str) -> bool:
    try:
        loc = page.locator(selector).first
        return bool(await loc.count()) and await loc.is_visible()
    except Exception:
        return False


async def feed_overlay_visible(page) -> bool:
    """Feed 详情浮层/侧栏已实际渲染（不能仅凭 URL 上的 modal_id）。"""
    for selector in _FEED_OVERLAY_SELECTORS:
        if await _locator_visible(page, selector):
            return True
    for selector in _COMMENT_SIDEBAR_MARKERS:
        if await _locator_visible(page, selector):
            return True
    return False


async def is_search_feed_overlay(page) -> bool:
    """搜索页 Feed 浮层：左视频 + 右评论侧栏（modal_id），非 /video/ 独立详情页。"""
    url = (page.url or "").lower()
    if re.search(r"/video/\d+", url):
        return False
    on_search = "/search/" in url or "/jingxuan/search/" in url
    if not on_search and "modal_id=" not in url:
        return False
    return await feed_overlay_visible(page)


async def search_list_visible(page) -> bool:
    """仍在搜索列表页（无 Feed 浮层）。"""
    url = (page.url or "").lower()
    if "/search/" not in url and "/jingxuan/search/" not in url:
        return False
    if re.search(r"/video/\d+", url):
        return False
    if await feed_overlay_visible(page):
        return False
    for selector in _SEARCH_LIST_POSTER_SELECTORS:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False


async def classify_douyin_page(page) -> dict[str, Any]:
    """综合 URL + DOM 判断当前页面阶段。"""
    url = page.url or ""
    url_l = url.lower()
    on_search = "/search/" in url_l or "/jingxuan/search/" in url_l
    on_video = bool(re.search(r"/video/\d+", url_l))
    has_modal_param = "modal_id=" in url_l
    feed_visible = await feed_overlay_visible(page)
    list_visible = await search_list_visible(page)

    if on_video:
        phase = "video_page"
    elif feed_visible:
        phase = "feed_detail"
    elif on_search and list_visible and not has_modal_param:
        phase = "search_list"
    elif on_search and has_modal_param and not feed_visible:
        phase = "search_list"
    elif on_search and list_visible:
        phase = "search_list"
    else:
        phase = "unknown"

    return {
        "phase": phase,
        "url": url,
        "on_search": on_search,
        "on_video": on_video,
        "has_modal_param": has_modal_param,
        "feed_visible": feed_visible,
        "list_visible": list_visible,
    }


async def wait_feed_detail(page, *, max_sec: float = 6.0) -> bool:
    deadline = asyncio.get_running_loop().time() + max_sec
    while asyncio.get_running_loop().time() < deadline:
        if await is_feed_detail_open(page):
            return True
        await asyncio.sleep(0.15)
    return False


async def is_feed_detail_open(page) -> bool:
    url = (page.url or "").lower()
    if re.search(r"/video/\d+", url):
        return True
    if await feed_overlay_visible(page):
        return True
    # 搜索页上可能有背景 video-player，不能单独作为详情判定
    if "/search/" not in url and "/jingxuan/search/" not in url:
        try:
            loc = page.locator('[data-e2e="video-player"]').first
            if await loc.count() and await loc.is_visible():
                return True
        except Exception:
            pass
    try:
        body = await page.locator("body").inner_text(timeout=1500)
        if "全部评论" in body and ("详情" in body or "相关推荐" in body):
            return True
    except Exception:
        pass
    return False


async def _has_visible_comment_items(page) -> bool:
    """侧栏须可见评论项，不能仅凭 DOM 里隐藏的 comment-item 判定已打开。"""
    for selector in (
        f'{_FEED_MODAL_COMMENT_ROOT} [data-e2e="comment-item"]',
        '[data-e2e="comment-item"]',
        '[class*="CommentItem"]',
    ):
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _comment_sidebar_active(page) -> bool:
    if await _has_visible_comment_items(page):
        return True
    try:
        header = page.locator('text=全部评论').first
        return await header.count() > 0 and await header.is_visible()
    except Exception:
        return False


_COMMENT_LIST_END_TEXTS = (
    "暂时没有更多评论",
    "没有更多评论",
)


async def comment_list_end_marker_visible(page) -> bool:
    """Comment sidebar footer shown when Douyin has no further pages to load."""
    for text in _COMMENT_LIST_END_TEXTS:
        try:
            loc = page.get_by_text(text, exact=False).first
            if not await loc.count():
                continue
            if await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _pause_feed_via_space(page) -> None:
    with contextlib.suppress(Exception):
        await page.keyboard.press("Space")
        await asyncio.sleep(0.25)


async def _click_comment_icon_via_dom(page) -> str:
    try:
        return str(await page.evaluate(_CLICK_COMMENT_ICON_JS) or "")
    except Exception:
        return ""


async def _try_click_comment_target(
    page,
    target,
    settings: Settings,
    *,
    tenant_id: str,
    timeout: float = 3500,
) -> bool:
    try:
        loc = target if not isinstance(target, str) else page.locator(target).first
        if not await loc.count() or not await loc.is_visible():
            return False
        await human_click(page, loc, settings, tenant_id=tenant_id, timeout=timeout)
        return True
    except Exception:
        return False


async def _wheel_comment_list_area(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    for selector in _COMMENT_WHEEL_TARGETS:
        loc = page.locator(selector).last
        try:
            if not await loc.count():
                continue
            if not await loc.is_visible():
                continue
            box = await loc.bounding_box()
            if not box:
                continue
            await page.mouse.move(
                box["x"] + box["width"] / 2,
                box["y"] + min(box["height"] / 2, 40),
            )
            await page.mouse.wheel(0, 520)
            await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
            return True
        except Exception:
            continue
    return False

_PAUSE_VIDEO_SELECTORS = (
    '[data-e2e="feed-active-video"] video',
    '[data-e2e="feed-active-video"] [data-e2e="video-player"]',
    '[data-e2e="video-player"]',
    "video",
)


async def pause_feed_video_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    """暂停 Feed 视频：单击播放器中部（模拟真人，不用 JS / Space）。"""
    for selector in _PAUSE_VIDEO_SELECTORS:
        try:
            loc = page.locator(selector).first
            if not await loc.count() or not await loc.is_visible():
                continue
            await human_click(page, loc, settings, tenant_id=tenant_id)
            await human_delay(page, settings, tenant_id=tenant_id, profile="action")
            return True
        except Exception:
            continue
    return False


async def activate_comment_sidebar_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    if await _comment_sidebar_active(page):
        return True

    # 搜索 Feed 浮层：右侧评论栏常已展开，勿点视频区域（易误触红心/暂停）
    search_feed = await is_search_feed_overlay(page)
    if search_feed and await _has_visible_comment_items(page):
        return True

    if not search_feed:
        await pause_feed_video_on_page(page, settings, tenant_id=tenant_id)
        await _pause_feed_via_space(page)

    for attempt in range(5):
        if await _comment_sidebar_active(page):
            return True

        for selector in _COMMENT_ICON_SELECTORS:
            if await _try_click_comment_target(
                page,
                selector,
                settings,
                tenant_id=tenant_id,
            ):
                await asyncio.sleep(0.45)
                if await _comment_sidebar_active(page) or await _has_visible_comment_items(page):
                    return True

        dom_hit = await _click_comment_icon_via_dom(page)
        if dom_hit:
            await asyncio.sleep(0.55)
            if await _comment_sidebar_active(page) or await _has_visible_comment_items(page):
                return True

        for selector in _COMMENT_TAB_SELECTORS:
            loc = page.locator(selector)
            count = await loc.count()
            for i in range(min(count, 5)):
                tab = loc.nth(i)
                try:
                    if not await tab.is_visible():
                        continue
                    text = re.sub(r"\s+", "", (await tab.inner_text() or ""))
                    if not text.startswith("评论"):
                        continue
                    if await _try_click_comment_target(
                        page,
                        tab,
                        settings,
                        tenant_id=tenant_id,
                    ):
                        await asyncio.sleep(0.45)
                        if await _comment_sidebar_active(page):
                            return True
                except Exception:
                    continue

        if not search_feed:
            await _pause_feed_via_space(page)
        await asyncio.sleep(0.35)

    return await _comment_sidebar_active(page) or await _has_visible_comment_items(page)


async def select_latest_comment_sort_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> bool:
    """评论侧栏默认「最热」时，切到「最新」以便按时间窗口采集。"""
    if not await _comment_sidebar_active(page):
        return False
    selectors = (
        '[data-e2e="comment-sort-latest"]',
        'span:text-is("最新")',
        'div[role="tab"]:has-text("最新")',
        'text=最新',
    )
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if not await loc.count() or not await loc.is_visible():
                continue
            await human_click(page, loc, settings, tenant_id=tenant_id)
            await human_delay(page, settings, tenant_id=tenant_id, profile="action")
            return True
        except Exception:
            continue
    return False


async def scroll_comment_sidebar_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    rounds: int = 1,
) -> bool:
    scrolled_any = False
    for _ in range(rounds):
        scrolled = await page.evaluate(COMMENT_SIDEBAR_SCROLL_JS)
        if scrolled:
            scrolled_any = True
        wheeled = await _wheel_comment_list_area(page, settings, tenant_id=tenant_id)
        if wheeled:
            scrolled_any = True
        if not scrolled_any:
            try:
                header = page.locator("text=全部评论").first
                if await header.count():
                    box = await header.bounding_box()
                    if box:
                        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 120)
                        await page.mouse.wheel(0, 520)
                        scrolled_any = True
                        await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
            except Exception:
                pass
        else:
            await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
    return scrolled_any


def merge_comment_api_pages(
    captured_pages: list[dict[str, Any]],
    *,
    max_comments: int,
) -> tuple[dict[str, dict[str, Any]], int, list[dict[str, Any]]]:
    comments_map: dict[str, dict[str, Any]] = {}
    api_total = 0
    for index, data in enumerate(captured_pages):
        if index == 0:
            api_total = int(data.get("total") or 0)
        for item in data.get("comments") or []:
            row = _normalize_comment(item)
            if row["comment_id"]:
                comments_map[row["comment_id"]] = row
                for reply in item.get("reply_comment") or []:
                    reply_row = _normalize_comment(reply, parent_comment_id=row["comment_id"])
                    if reply_row["comment_id"]:
                        comments_map[reply_row["comment_id"]] = reply_row

    comments = list(comments_map.values())
    comments.sort(key=lambda row: row.get("create_time") or 0, reverse=True)
    top_rows = [row for row in comments if not row.get("parent_comment_id")][:max_comments]
    return comments_map, api_total, top_rows


_REPLY_EXPAND_SELECTORS = (
    'span:has-text("条回复")',
    'div:has-text("条回复")',
    'button:has-text("条回复")',
    'span:has-text("展开")',
    'text=/展开\\d*条回复/',
    'text=/\\d+\\s*条回复/',
    'text=/查看更多回复/',
)


async def find_comment_item_locator(
    page,
    *,
    comment_id: str = "",
    comment_text: str = "",
):
    """定位评论 DOM：优先 comment_id / #comment-{id}，其次文本匹配。"""
    needle = (comment_text or "").strip()[:40]
    cid = (comment_id or "").strip()

    if cid:
        id_selectors = (
            f'[data-e2e="comment-item"][data-cid="{cid}"]',
            f'[data-e2e="comment-item"]:has(#comment-{cid})',
            f'[class*="CommentItem"][data-cid="{cid}"]',
            f"#comment-{cid}",
        )
        for selector in id_selectors:
            loc = page.locator(selector).first
            try:
                if not await loc.count():
                    continue
                if selector.startswith("#comment-"):
                    wrapped = page.locator(f'[data-e2e="comment-item"]:has(#comment-{cid})').first
                    if await wrapped.count():
                        return wrapped
                    reply_wrap = page.locator(f'[class*="reply"]:has(#comment-{cid})').first
                    if await reply_wrap.count():
                        return reply_wrap
                with contextlib.suppress(Exception):
                    await loc.scroll_into_view_if_needed(timeout=5000)
                if await loc.is_visible():
                    return loc
            except Exception:
                continue

    selectors = (
        '[data-e2e="comment-item"]',
        '[class*="CommentItem"]',
        '[class*="reply-comment"]',
        '[class*="ReplyComment"]',
    )
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for index in range(count):
            item = loc.nth(index)
            try:
                dom_cid = (await item.get_attribute("data-cid")) or ""
                if cid and (dom_cid == cid or cid in dom_cid):
                    return item
                if needle:
                    text = (await item.inner_text(timeout=1500)) or ""
                    if needle in text:
                        return item
                    for token in needle.replace("@", " ").split():
                        token = token.strip()
                        if len(token) >= 2 and token in text:
                            return item
            except Exception:
                continue
    return None


async def expand_replies_for_parent_comment(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    parent_comment_id: str = "",
    parent_item=None,
    max_clicks: int = 3,
) -> bool:
    """滚到父评论并点击「展开 N 条回复」，以便定位楼中楼目标评论。"""
    parent_id = str(parent_comment_id or "").strip()
    item = parent_item
    if item is None and parent_id:
        item = await find_comment_item_locator(page, comment_id=parent_id)
    if item is None:
        return False

    with contextlib.suppress(Exception):
        await item.scroll_into_view_if_needed(timeout=5000)
    await human_delay(page, settings, tenant_id=tenant_id, profile="action")

    expanded = False
    for _ in range(max(1, max_clicks)):
        clicked = False
        for selector in _REPLY_EXPAND_SELECTORS:
            loc = item.locator(selector).first
            try:
                if await loc.count() and await loc.is_visible():
                    await human_click(page, loc, settings, tenant_id=tenant_id)
                    clicked = True
                    expanded = True
                    await human_delay(page, settings, tenant_id=tenant_id, profile="action")
                    break
            except Exception:
                continue
        if clicked:
            continue
        with contextlib.suppress(Exception):
            if await item.evaluate(
                """(el) => {
                  for (const node of el.querySelectorAll('span, div, button, a')) {
                    const text = (node.textContent || '').trim();
                    if (/展开\\d*条回复|\\d+\\s*条回复|查看更多回复/.test(text)) {
                      node.click();
                      return true;
                    }
                  }
                  return false;
                }"""
            ):
                expanded = True
                await human_delay(page, settings, tenant_id=tenant_id, profile="action")
                continue
        break
    return expanded


async def scroll_comment_sidebar_until(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    comment_id: str = "",
    comment_text: str = "",
    parent_comment_id: str = "",
    max_rounds: int = 8,
):
    """分页滚动侧栏直到目标评论可见；楼中楼会先展开父评论回复区。"""
    parent_id = str(parent_comment_id or "").strip()

    async def _locate_target():
        if parent_id:
            parent = await find_comment_item_locator(page, comment_id=parent_id)
            if parent is not None:
                await expand_replies_for_parent_comment(
                    page,
                    settings,
                    tenant_id=tenant_id,
                    parent_item=parent,
                )
        return await find_comment_item_locator(
            page,
            comment_id=comment_id,
            comment_text=comment_text,
        )

    await activate_comment_sidebar_on_page(page, settings, tenant_id=tenant_id)
    target = await _locate_target()
    if target is not None:
        return target

    for _ in range(max(1, max_rounds)):
        await scroll_comment_sidebar_on_page(page, settings, tenant_id=tenant_id, rounds=1)
        target = await _locate_target()
        if target is not None:
            return target
    return None


async def close_feed_detail_on_page(
    page,
    settings: Settings,
    *,
    tenant_id: str,
) -> None:
    if not await is_feed_detail_open(page):
        return
    for selector in _CLOSE_FEED_SELECTORS:
        btn = page.locator(selector).first
        try:
            if await btn.count() and await btn.is_visible():
                await human_click(page, btn, settings, tenant_id=tenant_id)
                await human_delay(page, settings, tenant_id=tenant_id, profile="action")
                return
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
        await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    except Exception:
        pass


def extract_comment_total_from_page_text(text: str) -> int | None:
    match = re.search(r"全部评论\s*\(?\s*(\d+)\s*\)?", text)
    if match:
        return int(match.group(1))
    return None
