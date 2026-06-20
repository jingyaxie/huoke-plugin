"""抖音独立浏览获客：关键词搜索 / 单视频 / 账号主页 → 评论 → 评估 → 触达。

与 skill / 智能体 / DouyinCommentCrawler 彼此独立，固定 UI 流程。

关键词模式 (keyword_auto)：
1. 打开 https://www.douyin.com/
2. 搜索框逐字输入关键词，Enter 搜索
3. 点击筛选，按 days 选发布时间
4. 按列表顺序点击视频（从第一个开始）

手动模式 (single_video / account_home)：
1. 打开抖音首页（复用稳定会话）
2. 单视频：直达 video_url；主页：打开 profile_url 并采集作品列表
3. 单视频 goto 详情；主页在作品网格上逐一点击进入详情（模拟人类）

共用后续步骤：
5. 打开评论侧栏，拦截 comment/list，评估符合意图的评论
6. 慢速滚动评论；命中则按 action_policy 分配 reply/dm/follow，保存精准线索
7. 评论过旧或看完 → 下一个视频，重复 5–7
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any, Literal

ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

from app.services.manual_acquisition_service import (
    MANUAL_ACQUISITION_MODES,
    infer_manual_url_mode,
    reconcile_manual_acquisition_mode,
)

StandaloneAcquisitionMode = Literal["keyword_auto", "single_video", "account_home"]

from playwright.async_api import Page
from sqlalchemy.orm import Session

from app.core.antibot import human_click, human_delay
from app.core.config import Settings
from app.platforms.douyin.human_guards import (
    HumanBrowseGuardError,
    assert_douyin_human_ready,
    is_captcha_page,
)
from app.platforms.douyin.js_constants import COMMENT_PATH, PLATFORM, _extract_aweme_id
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.douyin.video_comments_passive import (
    _days_cutoff_ts,
    _filter_comments_by_days,
    _last_list_page,
    _merge_captured_pages,
    _newest_top_create_time_in_page,
    _page_signature,
    comment_scroll_stop_reason,
)
from app.services.outreach_policy import OutreachAction, choose_outreach_action, random_interval_sec
from app.services.supervisor_outreach import persist_crawl_skill_result
from app.services.ui_flow.step_overlay import clear_page_step_hint, set_page_step_hint
from app.services.ui_flow.params import parse_ui_flow_params
from app.services.ui_flow.platforms.douyin.feed_ui import (
    _comment_sidebar_active,
    activate_comment_sidebar_on_page,
    classify_douyin_page,
    close_feed_detail_on_page,
    comment_list_end_marker_visible,
    feed_overlay_visible,
    is_feed_detail_open,
    is_search_feed_overlay,
    scroll_comment_sidebar_on_page,
    search_list_visible,
    select_latest_comment_sort_on_page,
    wait_feed_detail,
)
from app.services.ui_flow.platforms.douyin.browse_ui import (
    _VIDEO_CARD_SELECTORS,
    _click_video_link_at_index,
    _open_feed_via_modal_id,
    _resolve_aweme_id_at_index,
    click_search_poster,
)
from app.services.ui_flow.platforms.douyin.profile_ui import (
    back_to_profile_list,
    click_profile_video_at_index,
    ensure_profile_item_index,
)
from app.platforms.search_filters import (
    douyin_publish_time_ui_label,
    filter_search_items,
    normalize_days,
    select_rows_after_filter,
)
from app.services.ui_flow.platforms.douyin.search_parse import (
    analyze_search_api_response,
    extract_aweme_items_from_json,
    is_search_result_api,
    mark_search_api_flags,
    rank_search_items,
    search_api_min_items,
)
from app.services.ui_flow.platforms.douyin.search_ui import (
    _POSTER_SELECTORS,
    _needs_ui_publish_filter,
    apply_ui_publish_time_filter,
    collect_video_urls_from_page,
    page_has_search_posters,
    page_has_video_results,
    release_searchbar_focus,
    reuse_search_results_if_ready,
    run_search,
    scroll_search_results_page,
)
from app.services.ui_flow.platforms.douyin.prepare_ui import run_prepare
from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession

CAPTURE_METHOD = "standalone_keyword_browse"
CAPTURE_METHOD_VIDEO = "standalone_video_browse"
CAPTURE_METHOD_PROFILE = "standalone_profile_browse"
DOUYIN_ENTRY_URL = "https://www.douyin.com/"
DOUYIN_JINGXUAN_URL = "https://www.douyin.com/jingxuan"


def capture_method_for_mode(mode: str) -> str:
    normalized = str(mode or "keyword_auto").strip().lower()
    if normalized == "single_video":
        return CAPTURE_METHOD_VIDEO
    if normalized == "account_home":
        return CAPTURE_METHOD_PROFILE
    return CAPTURE_METHOD


def _is_keyword_mode(config: "StandaloneKeywordBrowseConfig") -> bool:
    return str(config.acquisition_mode or "keyword_auto").strip().lower() == "keyword_auto"


def _is_manual_mode(config: "StandaloneKeywordBrowseConfig") -> bool:
    return str(config.acquisition_mode or "").strip().lower() in MANUAL_ACQUISITION_MODES


def _result_subject(config: "StandaloneKeywordBrowseConfig") -> str:
    if config.acquisition_mode == "single_video":
        return str(config.video_url or "").strip()
    if config.acquisition_mode == "account_home":
        return str(config.profile_url or "").strip()
    return str(config.keyword or "").strip()


def validate_standalone_config(config: "StandaloneKeywordBrowseConfig") -> tuple[bool, str]:
    mode = str(config.acquisition_mode or "keyword_auto").strip().lower()
    if mode == "keyword_auto":
        if not str(config.keyword or "").strip():
            return False, "关键词模式需要 keyword"
        return True, ""
    if mode == "single_video":
        if not str(config.video_url or "").strip():
            return False, "单视频模式需要 video_url"
        return True, ""
    if mode == "account_home":
        if not str(config.profile_url or "").strip():
            return False, "主页模式需要 profile_url"
        return True, ""
    return False, f"不支持的 acquisition_mode: {mode}"


def resolve_standalone_acquisition_mode(
    *,
    acquisition_mode: str | None,
    input_url: str = "",
    video_url: str = "",
    profile_url: str = "",
) -> tuple[str, str, str]:
    """归一化手动/关键词模式与 URL 字段。"""
    raw_mode = str(acquisition_mode or "keyword_auto").strip().lower()
    resolved_video = str(video_url or "").strip()
    resolved_profile = str(profile_url or "").strip()
    resolved_input = str(input_url or "").strip()
    if not resolved_video and raw_mode == "single_video":
        resolved_video = resolved_input
    if not resolved_profile and raw_mode == "account_home":
        resolved_profile = resolved_input
    if raw_mode in MANUAL_ACQUISITION_MODES:
        source = resolved_video or resolved_profile or resolved_input
        if source:
            raw_mode = reconcile_manual_acquisition_mode(raw_mode, source, "douyin")
            inferred = infer_manual_url_mode(source, "douyin")
            if inferred == "single_video":
                resolved_video = resolved_video or source
            elif inferred == "account_home":
                resolved_profile = resolved_profile or source
    if raw_mode == "single_video" and not resolved_video and resolved_input:
        resolved_video = resolved_input
    if raw_mode == "account_home" and not resolved_profile and resolved_input:
        resolved_profile = resolved_input
    return raw_mode, resolved_video, resolved_profile


def _on_search_results_url(url: str) -> bool:
    u = (url or "").lower()
    return "/search/" in u or "/jingxuan/search/" in u


def _sync_search_aweme_ids_from_api(
    ctx: DouyinUiSession,
    api_items: dict[str, dict],
    *,
    days: int | None = None,
    api_days_fallback: bool = False,
) -> list[str]:
    """用拦截到的 search/single API 顺序确定要点哪个视频（不依赖 DOM href）。"""
    if not api_items:
        return list(ctx.state.get("search_aweme_ids") or [])
    ranked = rank_search_items(list(api_items.values()), ctx.params.keyword)
    nd = normalize_days(days)
    if api_days_fallback and nd:
        filtered, stats = filter_search_items(
            ranked,
            region=ctx.params.region,
            days=nd,
            platform="douyin",
            limit=max(len(ranked), int(ctx.params.content_limit or 5) * 3),
        )
        filtered_ranked = select_rows_after_filter(
            ranked,
            filtered,
            region=ctx.params.region,
            limit=max(len(ranked), int(ctx.params.content_limit or 5) * 3),
        )
        ctx.phase_log.append(
            "SEARCH_API_DAYS_FALLBACK "
            f"matched={stats.get('matched', 0)}/{stats.get('scanned', 0)} days={nd}"
        )
        if filtered_ranked:
            ranked = filtered_ranked
        else:
            ctx.phase_log.append("SEARCH_API_DAYS_FALLBACK empty_keep_dom_order")
    aweme_ids = [str(row.get("aweme_id") or "") for row in ranked if str(row.get("aweme_id") or "")]
    if aweme_ids:
        ctx.state["search_aweme_ids"] = aweme_ids
        ctx.state["search_poster_mode"] = True
    return aweme_ids


def _publish_days_for_config(config: StandaloneKeywordBrowseConfig) -> int | None:
    raw = config.video_publish_days if config.video_publish_days is not None else config.days
    return normalize_days(raw)


def _publish_filter_ui_label(config: StandaloneKeywordBrowseConfig) -> str | None:
    return douyin_publish_time_ui_label(_publish_days_for_config(config))


def _log_search_filter_state(ctx: DouyinUiSession) -> None:
    applied = ctx.state.get("search_filter_applied")
    verified = ctx.state.get("search_filter_verified")
    steps = ctx.state.get("search_filter_steps") or []
    parts: list[str] = []
    if applied:
        parts.append(f"label={applied}")
    parts.append(f"verified={verified}")
    if steps:
        parts.append("steps=" + ">".join(str(s) for s in steps))
    ctx.phase_log.append("SEARCH_FILTER " + " ".join(parts))


def _filter_diagnostic_suffix(ctx: DouyinUiSession) -> str:
    applied = ctx.state.get("search_filter_applied")
    verified = ctx.state.get("search_filter_verified")
    steps = ctx.state.get("search_filter_steps") or []
    if applied:
        suffix = f"；发布时间={applied}"
        if verified:
            return suffix + "（已确认）"
        if steps and "verified=weak" in steps:
            return suffix + "（弱确认）"
        return suffix + "（未确认）"
    if _needs_ui_publish_filter(ctx):
        if steps:
            return f"；筛选步骤={'>'.join(str(s) for s in steps)}"
        return "；筛选未生效"
    return ""


async def _is_search_list_ready(
    page: Page,
    api_items: dict[str, dict],
    *,
    ctx: DouyinUiSession | None = None,
) -> bool:
    """列表已展示即视为搜索成功：search API 有明确结论，或 DOM 海报/链接可见。"""
    if not _on_search_results_url(page.url or ""):
        return False
    if api_items:
        return True
    if ctx and ctx.state.get("search_api_complete"):
        return True
    return bool(await page_has_search_posters(page) or await page_has_video_results(page))


async def _page_phase_note(page: Page) -> str:
    snap = await classify_douyin_page(page)
    return (
        f"phase={snap.get('phase')} feed={snap.get('feed_visible')} "
        f"list={snap.get('list_visible')} modal_param={snap.get('has_modal_param')}"
    )


async def _wait_feed_opened(page: Page, *, max_sec: float = 4.0) -> bool:
    """等待搜索页 Feed 浮层（左视频右评论），不接受 /video/ 独立详情页。"""
    deadline = asyncio.get_running_loop().time() + max_sec
    while asyncio.get_running_loop().time() < deadline:
        if await is_search_feed_overlay(page):
            return True
        await asyncio.sleep(0.15)
    return False


async def _wait_search_feed_overlay(
    ctx: DouyinUiSession,
    *,
    aweme_hint: str = "",
    max_sec: float = 5.0,
) -> bool:
    """等待搜索 Feed 浮层；若误入 /video/ 详情页则尝试 modal_id 恢复。"""
    page = ctx.page
    deadline = asyncio.get_running_loop().time() + max_sec
    tried_modal_recovery = False
    while asyncio.get_running_loop().time() < deadline:
        if await is_search_feed_overlay(page):
            ctx.state["feed_mode"] = True
            return True
        url = (page.url or "").lower()
        if (
            aweme_hint
            and re.search(r"/video/\d+", url)
            and not tried_modal_recovery
        ):
            tried_modal_recovery = True
            if await _open_feed_via_modal_id(ctx, aweme_hint):
                await asyncio.sleep(0.45)
                continue
        await asyncio.sleep(0.15)
    return False


async def _search_list_visible(page: Page) -> bool:
    if not _on_search_results_url(page.url or ""):
        return False
    if "modal_id=" in (page.url or "").lower() and await feed_overlay_visible(page):
        return False
    return await search_list_visible(page)


async def _back_to_search_list(ctx: DouyinUiSession) -> bool:
    """从 Feed 回到搜索列表，准备点下一个 item。返回 True 表示列表可继续点击。"""
    page = ctx.page
    settings = ctx.settings
    tenant_id = ctx.tenant_id

    if await _search_list_visible(page):
        ctx.state["feed_mode"] = False
        return True

    on_search = _on_search_results_url(page.url or "")
    if on_search and await _count_search_posters(page) > 0:
        ctx.state["feed_mode"] = False
        return True

    if ctx.state.get("feed_mode") or "modal_id=" in (page.url or "").lower() or (
        not on_search and await is_feed_detail_open(page)
    ):
        for _ in range(2):
            with contextlib.suppress(Exception):
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.18)
        await close_feed_detail_on_page(page, settings, tenant_id=tenant_id)
        ctx.state["feed_mode"] = False

    if _on_search_results_url(page.url or ""):
        for _ in range(15):
            if await _search_list_visible(page):
                await release_searchbar_focus(page)
                return True
            with contextlib.suppress(Exception):
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.12)

    search_url = str(ctx.state.get("search_url") or "")
    if search_url and not await page_has_search_posters(page):
        need_goto = (
            "/search/" not in (page.url or "").lower()
            or "modal_id=" in (page.url or "").lower()
            or await is_feed_detail_open(page)
        )
        if need_goto:
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
            except Exception:
                pass
            for _ in range(10):
                if await _search_list_visible(page):
                    await release_searchbar_focus(page)
                    return True
                await asyncio.sleep(0.12)

    await release_searchbar_focus(page)
    return await _search_list_visible(page)


_CLICK_POSTER_SELECTORS = (
    '[class*="discover-video-card"]',
    'img.discover-video-card-img',
    '[class*="search-result-card"]',
    'div.search-result-card',
    '[data-e2e="search-card-video"]',
    '[class*="SearchVideoCard"]',
    *_VIDEO_CARD_SELECTORS,
)

_VISIBLE_SEARCH_CARDS_JS = """
() => {
  const out = [];
  const seen = new Set();
  const isInViewport = (r) => (
    r.width >= 24 && r.height >= 24 &&
    r.bottom > 8 && r.top < window.innerHeight - 8 &&
    r.right > 8 && r.left < window.innerWidth - 8
  );
  const pickNode = (el) => {
    const chain = [
      el.closest('[class*="discover-video-card"]'),
      el.closest('[data-e2e="search-card-video"]'),
      el.closest('[class*="search-result-card"]'),
      el.closest('div.search-result-card'),
      el.closest('[class*="SearchVideoCard"]'),
      el.closest('a[href*="/video/"]'),
      el.tagName === 'IMG' ? el.parentElement : null,
      el,
    ];
    for (const node of chain) {
      if (!node) continue;
      const r = node.getBoundingClientRect();
      if (r.width >= 24 && r.height >= 24) return { node, rect: r };
    }
    return null;
  };
  const selectors = [
    '[class*="discover-video-card"]',
    'img.discover-video-card-img',
    '[data-e2e="search-card-video"]',
    'div.search-result-card',
    '[class*="search-result-card"]',
    '[class*="SearchVideoCard"]',
    '[class*="videoImage"] img',
    'a[href*="/video/"]',
  ];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      const picked = pickNode(el);
      if (!picked || !isInViewport(picked.rect)) continue;
      const r = picked.rect;
      const key = `${Math.round(r.top)}:${Math.round(r.left)}:${Math.round(r.width)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const hrefEl = el.closest('a[href*="/video/"]')
        || el.querySelector?.('a[href*="/video/"]')
        || (el.href ? el : null);
      const href = hrefEl?.href || el.href || '';
      let aweme = (String(href).match(/\\/video\\/(\\d{8,22})/) || [])[1] || '';
      if (!aweme) {
        const holder = el.closest('[data-aweme-id]') || el;
        aweme = String(holder.getAttribute('data-aweme-id') || '').trim();
      }
      out.push({
        top: r.top,
        left: r.left,
        width: r.width,
        height: r.height,
        aweme,
        selector: sel,
      });
    }
  }
  out.sort((a, b) => a.top - b.top || a.left - b.left);
  return out;
}
"""

_CLICK_SEARCH_CARD_JS = """
(index) => {
  const selectors = [
    '[class*="discover-video-card"]',
    'div.search-result-card',
    '[data-e2e="search-card-video"]',
    '[class*="search-result-card"]',
    '[class*="SearchVideoCard"]',
    '[class*="videoImage"] img',
  ];
  for (const sel of selectors) {
    const nodes = Array.from(document.querySelectorAll(sel));
    if (nodes.length <= index) continue;
    let target = nodes[index];
    if (target.tagName === 'IMG') {
      target = target.closest(
        '[class*="discover-video-card"], [data-e2e="search-card-video"], '
        + '[class*="search-result-card"], [class*="SearchVideoCard"]'
      ) || target.parentElement || target;
    }
    target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
    const r = target.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    if (typeof target.click === 'function') target.click();
    else {
      target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    }
    const href = (target.closest('a[href*="/video/"]') || target.querySelector('a[href*="/video/"]'))?.href || '';
    let aweme = (String(href).match(/\\/video\\/(\\d{8,22})/) || [])[1] || '';
    if (!aweme) {
      const holder = target.closest('[data-aweme-id]') || target;
      aweme = String(holder.getAttribute('data-aweme-id') || '').trim();
    }
    return { ok: true, selector: sel, total: nodes.length, aweme, top: r.top, left: r.left };
  }
  return { ok: false, selector: '', total: 0, aweme: '', top: 0, left: 0 };
}
"""


async def _click_search_card_via_js(ctx: DouyinUiSession, index: int) -> tuple[bool, str, str]:
    """虚拟列表：按 DOM 序号 scrollIntoView 后 JS 点击。"""
    page = ctx.page
    try:
        result = await page.evaluate(_CLICK_SEARCH_CARD_JS, index)
    except Exception as exc:
        return False, f"js_click_failed:{exc}", ""
    if not isinstance(result, dict) or not result.get("ok"):
        total = int((result or {}).get("total") or 0) if isinstance(result, dict) else 0
        return False, f"js_click_miss index={index} total={total}", ""
    aweme = str(result.get("aweme") or "")
    sel = str(result.get("selector") or "js_card")
    await asyncio.sleep(random.uniform(0.35, 0.65))
    if await _wait_feed_opened(page, max_sec=5.0):
        ctx.state["feed_mode"] = True
        return True, f"js_click:{sel} index={index} total={result.get('total')}", aweme
    top = float(result.get("top") or 0)
    left = float(result.get("left") or 0)
    if top > 0 and left > 0:
        await page.mouse.click(left + 40, top + 40)
        if await _wait_feed_opened(page, max_sec=3.0):
            ctx.state["feed_mode"] = True
            return True, f"js_coord:{sel} index={index}", aweme
    return False, f"js_clicked_no_feed:{sel}[{index}]", aweme


async def _collect_visible_search_cards(page: Page) -> list[dict[str, Any]]:
    try:
        cards = await page.evaluate(_VISIBLE_SEARCH_CARDS_JS)
    except Exception:
        return []
    return cards if isinstance(cards, list) else []


_SEARCH_CARD_PICK_JS = _VISIBLE_SEARCH_CARDS_JS


async def _scroll_search_until_card_index(
    ctx: DouyinUiSession,
    index: int,
    *,
    max_scrolls: int | None = None,
) -> list[dict[str, Any]]:
    """虚拟列表下滚动直到第 index 个可见卡片出现（仅在搜索列表页执行）。"""
    page = ctx.page
    aweme_ids = list(ctx.state.get("search_aweme_ids") or [])
    if len(aweme_ids) > index:
        return await _collect_visible_search_cards(page)

    if not await search_list_visible(page):
        return await _collect_visible_search_cards(page)

    budget = max_scrolls
    if budget is None:
        budget = 2 if len(aweme_ids) > index else min(12, max(2, index + 1))

    cards: list[dict[str, Any]] = []
    scroll_budget = 0 if index <= 0 else budget
    for _ in range(scroll_budget + 1):
        cards = await _collect_visible_search_cards(page)
        if len(cards) > index:
            return cards
        if await feed_overlay_visible(page) or not await search_list_visible(page):
            break
        if scroll_budget <= 0:
            break
        scroll_budget -= 1
        await scroll_search_results_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        await asyncio.sleep(0.35)
    return cards


async def _resolve_best_poster_selector(page: Page, index: int) -> tuple[str, int]:
    """找出能覆盖 index 且可见条目最多的海报选择器。"""
    best_selector = ""
    best_count = 0
    best_score = -1
    for selector in (
        '[class*="discover-video-card"]',
        'img.discover-video-card-img',
        'div.search-result-card',
        '[class*="search-result-card"]',
        '[data-e2e="search-card-video"]',
        '[class*="SearchVideoCard"]',
        '[class*="videoImage"] img',
        *_VIDEO_CARD_SELECTORS,
        *_POSTER_SELECTORS,
    ):
        try:
            loc = page.locator(selector)
            count = await loc.count()
        except Exception:
            continue
        if count <= index:
            continue
        visible = 0
        for i in range(min(count, max(index + 1, 6))):
            try:
                if await loc.nth(i).is_visible():
                    visible += 1
            except Exception:
                continue
        score = visible * 1000 + count
        if score > best_score:
            best_score = score
            best_count = count
            best_selector = selector
    return best_selector, best_count


async def _click_visible_card_coords(
    page: Page,
    card: dict[str, Any],
    *,
    settings: Settings,
    tenant_id: str,
) -> bool:
    x = float(card.get("left") or 0) + float(card.get("width") or 0) / 2
    y = float(card.get("top") or 0) + float(card.get("height") or 0) / 2
    await page.mouse.move(x, y)
    await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
    await page.mouse.click(x, y)
    return await _wait_feed_opened(page, max_sec=4.0)


async def _click_search_img_poster(ctx: DouyinUiSession, index: int) -> tuple[bool, str]:
    """点击搜索列表封面（优先可见卡片坐标，兼容精选页虚拟列表）。"""
    page = ctx.page
    cards = await _scroll_search_until_card_index(ctx, index)
    if len(cards) > index:
        card = cards[index]
        if await _click_visible_card_coords(
            page,
            card,
            settings=ctx.settings,
            tenant_id=ctx.tenant_id,
        ):
            ctx.state["feed_mode"] = True
            sel = str(card.get("selector") or "visible_card")
            return True, f"visible_coord:{sel} index={index}"

    selector, count = await _resolve_best_poster_selector(page, index)
    if not selector:
        return False, f"img_click_no_target count={count} visible={len(cards)}"
    target = page.locator(selector).nth(index)
    if " img" in selector or "discover-video-card-img" in selector:
        parent = target.locator(
            "xpath=ancestor::*[@data-e2e='search-card-video' or "
            "contains(@class,'search-result-card') or contains(@class,'SearchVideoCard') or "
            "contains(@class,'discover-video-card')][1]"
        )
        if await parent.count():
            target = parent.first
    try:
        if await target.is_visible():
            await target.scroll_into_view_if_needed(timeout=3000)
            try:
                await human_click(page, target, ctx.settings, tenant_id=ctx.tenant_id)
            except Exception:
                await target.click(force=True, timeout=4000)
        else:
            box = await target.bounding_box()
            if box:
                await page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )
            else:
                await target.click(force=True, timeout=4000)
        if await _wait_feed_opened(page, max_sec=5.0):
            ctx.state["feed_mode"] = True
            return True, f"img_click:{selector} index={index}"
    except Exception as exc:
        box = await target.bounding_box()
        if box:
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            await page.mouse.click(x, y)
            if await _wait_feed_opened(page, max_sec=5.0):
                ctx.state["feed_mode"] = True
                return True, f"img_coord:{selector} index={index}"
        return False, f"img_click_fail:{selector}[{index}] {exc}"
    return False, f"img_click_no_feed:{selector}[{index}] visible={len(cards)}"


async def _click_search_card_via_dom(
    ctx: DouyinUiSession,
    index: int,
) -> tuple[bool, str, str]:
    """用页面内可见卡片坐标点击（兼容精选页 discover-video-card）。"""
    page = ctx.page
    try:
        cards = await _scroll_search_until_card_index(ctx, index)
    except Exception as exc:
        return False, f"dom_pick_failed:{exc}", ""
    if not isinstance(cards, list) or len(cards) <= index:
        return False, f"dom_cards={len(cards) if isinstance(cards, list) else 0}", ""
    card = cards[index]
    aweme = str(card.get("aweme") or "")
    if await _click_visible_card_coords(
        page,
        card,
        settings=ctx.settings,
        tenant_id=ctx.tenant_id,
    ):
        ctx.state["feed_mode"] = True
        return True, f"dom_click index={index} aweme={aweme[:12] if aweme else 'dom'}", aweme
    return False, f"dom_clicked_no_feed index={index}", aweme


async def _click_search_result_item(
    ctx: DouyinUiSession,
    index: int,
    *,
    skip_back: bool = False,
) -> tuple[bool, str]:
    """点击搜索列表第 N 个视频：aweme 直开优先，DOM 点击兜底；每步校验页面阶段。"""
    page = ctx.page
    if not skip_back:
        if not await _back_to_search_list(ctx):
            return False, "未能返回搜索列表"
    else:
        await asyncio.sleep(random.uniform(0.12, 0.28))

    await _sync_search_aweme_ids_from_dom(ctx)
    aweme_hint = await _resolve_aweme_id_at_index(ctx, index)
    phase_before = await _page_phase_note(page)
    ctx.phase_log.append(
        f"CLICK_PREP index={index} posters={await _count_search_posters(page)} "
        f"best={await _resolve_best_poster_selector(page, index)} aweme={aweme_hint[:12] if aweme_hint else 'none'} "
        f"{phase_before}"
    )

    async def _confirm_feed_open(method: str) -> tuple[bool, str]:
        snap = await classify_douyin_page(page)
        if await _wait_search_feed_overlay(ctx, aweme_hint=aweme_hint, max_sec=5.0):
            return True, (
                f"{method} index={index} aweme={aweme_hint[:12] if aweme_hint else 'dom'} "
                f"feed_overlay phase={snap.get('phase')}"
            )
        snap = await classify_douyin_page(page)
        return False, (
            f"{method}_no_feed_overlay index={index} phase={snap.get('phase')} "
            f"feed={snap.get('feed_visible')} list={snap.get('list_visible')} "
            f"url={(page.url or '')[:96]}"
        )

    if aweme_hint and await _open_feed_via_modal_id(ctx, aweme_hint):
        ok, note = await _confirm_feed_open("modal_open")
        if ok:
            return True, note

    if not await search_list_visible(page):
        return False, f"无法 DOM 点击：当前不在搜索列表；{await _page_phase_note(page)}"

    last_note = f"未找到可点击的列表 item；api_aweme={aweme_hint or 'none'}"

    # 已有 aweme_id 时优先 modal 打开，避免在列表上反复滚动
    if index > 0 and not aweme_hint:
        await scroll_search_results_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        await asyncio.sleep(0.35)

    js_ok, js_note, js_aweme = await _click_search_card_via_js(ctx, index)
    if js_ok:
        ok, note = await _confirm_feed_open(js_note.split()[0] if js_note else "js_click")
        if ok:
            if js_aweme and not aweme_hint:
                ids = list(ctx.state.get("search_aweme_ids") or [])
                if js_aweme not in ids:
                    ids.append(js_aweme)
                    ctx.state["search_aweme_ids"] = ids
            return True, note
        last_note = note

    img_ok, img_note = await _click_search_img_poster(ctx, index)
    if img_ok:
        ok, note = await _confirm_feed_open(img_note.split(":")[0] if img_note else "img_click")
        if ok:
            return True, note
        last_note = note

    dom_ok, dom_note, dom_aweme = await _click_search_card_via_dom(ctx, index)
    if dom_ok:
        ok, note = await _confirm_feed_open("dom_click")
        if ok:
            if dom_aweme and not aweme_hint:
                ids = list(ctx.state.get("search_aweme_ids") or [])
                if dom_aweme not in ids:
                    ids.append(dom_aweme)
                    ctx.state["search_aweme_ids"] = ids
            return True, note
        last_note = note
    elif dom_note:
        last_note = f"{last_note}; {dom_note}"

    if await click_search_poster(ctx, index):
        ok, note = await _confirm_feed_open("browse_ui_poster")
        if ok:
            return True, note
        last_note = note

    best_selector = ""
    best_count = 0
    for selector in _CLICK_POSTER_SELECTORS:
        try:
            count = await page.locator(selector).count()
        except Exception:
            continue
        if count > index and count > best_count:
            best_count = count
            best_selector = selector

    if best_selector:
        item = page.locator(best_selector).nth(index)
        try:
            with contextlib.suppress(Exception):
                await page.evaluate(
                    """(args) => {
                      const [sel, idx] = args;
                      const nodes = Array.from(document.querySelectorAll(sel));
                      const el = nodes[idx];
                      if (el) el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
                    }""",
                    [best_selector, index],
                )
                await asyncio.sleep(0.3)
            if await item.is_visible():
                await human_click(page, item, ctx.settings, tenant_id=ctx.tenant_id)
            else:
                await item.click(force=True, timeout=4000)
            ok, note = await _confirm_feed_open(f"poster_click:{best_selector}")
            if ok:
                return True, note
            last_note = note
        except Exception as exc:
            last_note = f"{best_selector}[{index}] 点击异常: {exc}"

    if await _click_video_link_at_index(ctx, index):
        ok, note = await _confirm_feed_open("link_click")
        if ok:
            return True, note
        last_note = note

    if aweme_hint and await _open_feed_via_modal_id(ctx, aweme_hint):
        ok, note = await _confirm_feed_open("modal_fallback")
        if ok:
            return True, note

    return False, f"{last_note}; {await _page_phase_note(page)}"


def _match_comment(comment_text: str, keywords: list[str], exclude: list[str] | None = None) -> bool:
    """简单关键词匹配，过滤招聘/广告等噪声。"""
    text = (comment_text or "").strip()
    if not text:
        return False
    exclude = exclude or []
    for word in exclude:
        if word and word in text:
            return False
    if not keywords:
        return True
    return any(k and k in text for k in keywords)


@dataclass
class StandaloneKeywordBrowseConfig:
    """独立浏览任务配置（不依赖 skill / agent）。"""

    keyword: str = ""
    acquisition_mode: StandaloneAcquisitionMode = "keyword_auto"
    video_url: str = ""
    profile_url: str = ""
    input_url: str = ""
    days: int = 7
    video_publish_days: int | None = None
    content_limit: int = 5
    target_precise_leads: int = 3
    max_videos_to_browse: int = 50
    comment_days: int | None = None
    region: str | None = None
    match_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_comment_length: int = 4
    max_comments_per_video: int = 300
    comment_scroll_rounds: int = 60
    watch_seconds_min: int = 3
    watch_seconds_max: int = 8
    action_policy: dict[str, Any] = field(
        default_factory=lambda: {
            "comment_ratio": 50,
            "dm_ratio": 30,
            "follow_ratio": 20,
            "interval_min_sec": 10,
            "interval_max_sec": 30,
        }
    )
    execute_outreach: bool = False
    test_all_outreach: bool = False
    reply_text: str = ""
    dm_text: str = ""
    persist_to_db: bool = True
    use_llm_eval: bool = False
    eval_spec: dict[str, Any] | None = None
    task_brief: Any | None = None
    reuse_stable_session: bool = True
    close_browser_after: bool = False
    start_video_index: int = 0
    resume_search_url: str = ""
    source_job_id: str = ""


@dataclass
class PreciseLeadRecord:
    """单条精准线索。"""

    comment_id: str
    comment_text: str
    username: str
    user_id: str
    sec_uid: str
    video_url: str
    aweme_id: str
    create_time: int
    match_score: float
    match_reason: str
    planned_action: OutreachAction
    outreach_executed: bool = False
    outreach_result: dict[str, Any] = field(default_factory=dict)
    raw_comment: dict[str, Any] = field(default_factory=dict)
    persisted: bool = False
    persist_error: str = ""


@dataclass
class StandaloneKeywordBrowseResult:
    ok: bool
    keyword: str
    acquisition_mode: str = "keyword_auto"
    source_url: str = ""
    search_url: str = ""
    videos_processed: int = 0
    comments_scanned: int = 0
    duplicates_skipped: int = 0
    precise_leads: list[PreciseLeadRecord] = field(default_factory=list)
    phase_log: list[str] = field(default_factory=list)
    diagnostic: str | None = None
    output_file: str | None = None
    error: str | None = None
    target_reached: bool = False
    search_exhausted: bool = False
    comments_persisted: int = 0


_logger = logging.getLogger(__name__)


async def _count_search_posters(page: Page) -> int:
    best = 0
    for selector in (*_POSTER_SELECTORS, *_VIDEO_CARD_SELECTORS):
        try:
            best = max(best, await page.locator(selector).count())
        except Exception:
            continue
    return best


async def _sync_search_aweme_ids_from_dom(ctx: DouyinUiSession) -> list[str]:
    """从搜索列表 DOM 链接或 data-aweme-id 补齐 aweme_id 顺序（API 未拦截时的兜底）。"""
    existing = list(ctx.state.get("search_aweme_ids") or [])
    if existing:
        return existing
    page = ctx.page
    try:
        dom_ids = await page.evaluate(
            """() => {
              const out = [];
              const seen = new Set();
              const nodes = document.querySelectorAll(
                '[data-aweme-id], [class*="discover-video-card"], div.search-result-card, [data-e2e="search-card-video"]'
              );
              for (const el of nodes) {
                const raw = String(el.getAttribute('data-aweme-id') || '').trim();
                if (/^\\d{8,22}$/.test(raw) && !seen.has(raw)) {
                  seen.add(raw);
                  out.push(raw);
                  continue;
                }
                const href = (el.closest('a[href*="/video/"]') || el.querySelector('a[href*="/video/"]'))?.href || '';
                const part = (String(href).match(/\\/video\\/(\\d{8,22})/) || [])[1] || '';
                if (/^\\d{8,22}$/.test(part) && !seen.has(part)) {
                  seen.add(part);
                  out.push(part);
                }
              }
              return out;
            }"""
        )
        if isinstance(dom_ids, list):
            ids = [str(i) for i in dom_ids if re.fullmatch(r"\d{8,22}", str(i))]
            if ids:
                ctx.state["search_aweme_ids"] = ids
                ctx.state["search_poster_mode"] = True
                return ids
    except Exception:
        pass
    try:
        cards = await page.evaluate(_SEARCH_CARD_PICK_JS)
        if isinstance(cards, list):
            ids: list[str] = []
            seen: set[str] = set()
            for card in cards:
                part = str((card or {}).get("aweme") or "")
                if re.fullmatch(r"\d{8,22}", part) and part not in seen:
                    seen.add(part)
                    ids.append(part)
            if ids:
                ctx.state["search_aweme_ids"] = ids
                ctx.state["search_poster_mode"] = True
                return ids
    except Exception:
        pass
    urls = await collect_video_urls_from_page(page, limit=max(10, int(ctx.params.content_limit or 5) * 3))
    ids: list[str] = []
    seen: set[str] = set()
    for url in urls:
        part = str(url or "").rstrip("/").split("/")[-1]
        if re.fullmatch(r"\d{8,22}", part) and part not in seen:
            seen.add(part)
            ids.append(part)
    if ids:
        ctx.state["search_aweme_ids"] = ids
        ctx.state["search_poster_mode"] = True
    return ids


async def _prepare_search_list_for_browse(ctx: DouyinUiSession) -> bool:
    """搜索完成后等待列表可点：确保在搜索页，DOM 海报或 API aweme_id 任一就绪。"""
    page = ctx.page
    settings = ctx.settings
    tenant_id = ctx.tenant_id
    search_url = str(ctx.state.get("search_url") or page.url or "")

    if search_url and not _on_search_results_url(page.url or ""):
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
        except Exception:
            pass

    deadline = asyncio.get_running_loop().time() + 28.0
    round_idx = 0
    while asyncio.get_running_loop().time() < deadline:
        aweme_ids = list(ctx.state.get("search_aweme_ids") or [])
        if aweme_ids:
            return True
        poster_count = await _count_search_posters(page)
        if poster_count > 0:
            await _sync_search_aweme_ids_from_dom(ctx)
            return True
        if ctx.video_urls:
            return True
        if round_idx % 3 == 2 and _on_search_results_url(page.url or ""):
            await scroll_search_results_page(page, settings, tenant_id=tenant_id)
        await human_delay(page, settings, tenant_id=tenant_id, profile="fast")
        round_idx += 1

    return bool(ctx.state.get("search_aweme_ids")) or await _count_search_posters(page) > 0


async def _open_feed_via_video_url(ctx: DouyinUiSession, aweme_id: str) -> bool:
    """无搜索列表 DOM 时，直链打开视频页作为兜底。"""
    if not aweme_id or not re.fullmatch(r"\d{8,22}", str(aweme_id)):
        return False
    page = ctx.page
    try:
        await page.goto(
            f"https://www.douyin.com/video/{aweme_id}",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        await human_delay(page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
        ctx.state["feed_mode"] = True
        return await wait_feed_detail(page, max_sec=6.0) or "/video/" in (page.url or "")
    except Exception:
        return False


async def _open_video_for_browse(
    ctx: DouyinUiSession,
    video_url: str,
    *,
    video_index: int,
) -> tuple[bool, str]:
    """手动模式：直达视频页并等待详情就绪。"""
    page = ctx.page
    settings = ctx.settings
    tenant_id = ctx.tenant_id
    url = str(video_url or "").strip()
    if not url:
        return False, f"视频 {video_index + 1} 缺少 URL"
    try:
        aweme_id = _extract_aweme_id(url)
    except ValueError:
        aweme_id = ""
    if aweme_id and "/video/" not in url:
        url = f"https://www.douyin.com/video/{aweme_id}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
        await assert_douyin_human_ready(
            page,
            settings,
            tenant_id=tenant_id,
            stage="video_url",
        )
        ctx.state["feed_mode"] = True
        if await wait_feed_detail(page, max_sec=6.0) or "/video/" in (page.url or ""):
            return True, f"open_video index={video_index + 1} url={url[:96]}"
        return False, f"视频页未就绪；{await _page_phase_note(page)}"
    except HumanBrowseGuardError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"打开视频失败: {exc}"


async def _prepare_manual_video_queue(
    ctx: DouyinUiSession,
    config: StandaloneKeywordBrowseConfig,
    store: DouyinSessionStore,
) -> tuple[bool, str, list[str]]:
    """单视频 / 主页模式：解析待浏览视频 URL 列表。"""
    mode = str(config.acquisition_mode or "").strip().lower()
    if mode == "single_video":
        url = str(config.video_url or config.input_url or "").strip()
        if not url:
            return False, "缺少 video_url", []
        return True, "", [url]

    if mode != "account_home":
        return False, f"不支持的手动模式: {mode}", []

    profile_url = str(config.profile_url or config.input_url or "").strip()
    if not profile_url:
        return False, "缺少 profile_url", []

    from app.platforms.douyin.profile_videos import DouyinProfileVideosTool

    limit = max(1, min(int(config.max_videos_to_browse), int(config.content_limit)))
    publish_days = config.video_publish_days if config.video_publish_days is not None else config.days
    tool = DouyinProfileVideosTool(
        ctx.settings,
        ctx.tenant_id,
        store,
        account_id=ctx.account_id,
    )
    captured_urls: list[str] = []
    await _report_step(
        ctx,
        "步骤 2/7：打开账号主页",
        sub=profile_url[:64],
        log=False,
    )
    videos, diagnostic, _capture = await tool.collect_videos_on_page(
        ctx.page,
        profile_url=profile_url,
        limit=limit,
        days=publish_days,
        captured_api_urls=captured_urls,
    )
    urls = [str(row.get("video_url") or "").strip() for row in videos if str(row.get("video_url") or "").strip()]
    if not urls:
        return False, diagnostic or "主页未采集到可浏览视频", []
    profile_aweme_ids: list[str] = []
    for url in urls:
        try:
            profile_aweme_ids.append(_extract_aweme_id(url))
        except ValueError:
            profile_aweme_ids.append(url.rstrip("/").split("/")[-1])
    ctx.state["profile_url"] = profile_url
    ctx.state["manual_video_urls"] = urls
    ctx.state["profile_aweme_ids"] = profile_aweme_ids
    ctx.phase_log.append(f"PROFILE_VIDEOS count={len(urls)} days={publish_days}")
    return True, diagnostic or "", urls


async def _enter_video_for_browse(
    ctx: DouyinUiSession,
    *,
    config: StandaloneKeywordBrowseConfig,
    video_index: int,
    video_url: str,
) -> tuple[bool, str]:
    """进入目标视频详情（关键词/主页列表点击 or 单视频直链）。"""
    mode = str(config.acquisition_mode or "").strip().lower()
    if mode == "account_home":
        if video_index > 0:
            if not await back_to_profile_list(ctx):
                return False, "未能返回主页列表，无法点下一个视频"
        else:
            await asyncio.sleep(random.uniform(0.12, 0.28))

        if not await ensure_profile_item_index(ctx, video_index):
            return False, f"主页列表第 {video_index + 1} 项不可用（滚动后仍不足）"

        aweme_hint = ""
        with contextlib.suppress(ValueError):
            aweme_hint = _extract_aweme_id(video_url)
        clicked, click_note = await click_profile_video_at_index(
            ctx,
            video_index,
            aweme_id=aweme_hint,
        )
        if not clicked:
            await _report_step(ctx, f"视频 {video_index + 1}：点击失败", sub=click_note, log=False)
            return False, f"未能点击主页第 {video_index + 1} 个视频；{click_note}"

        snap_after = await classify_douyin_page(ctx.page)
        ctx.phase_log.append(
            f"PAGE_AFTER_PROFILE_CLICK phase={snap_after.get('phase')} feed={snap_after.get('feed_visible')} "
            f"url={str(ctx.page.url or '')[:96]}"
        )
        if not await wait_feed_detail(ctx.page, max_sec=4.0):
            await _report_step(ctx, "详情页未就绪", sub=await _page_phase_note(ctx.page), log=False)
            return False, f"点击主页视频后 Feed 未就绪；{await _page_phase_note(ctx.page)}"

        ctx.phase_log.append(f"PROFILE_ITEM_CLICK index={video_index} {click_note}")
        await _report_step(
            ctx,
            f"步骤 4/7：点击主页第 {video_index + 1} 个视频",
            sub=click_note[:48] if click_note else "进入详情…",
            log=False,
        )
        return True, click_note

    if mode == "single_video":
        opened, note = await _open_video_for_browse(ctx, video_url, video_index=video_index)
        if opened:
            await _report_step(
                ctx,
                f"步骤 3/7：打开视频 {video_index + 1}",
                sub=note[:48] if note else "进入详情…",
                log=False,
            )
        return opened, note

    if not await _back_to_search_list(ctx):
        return False, "未能返回搜索列表，无法点下一个视频"

    aweme_hint = ""
    with contextlib.suppress(ValueError):
        aweme_hint = _extract_aweme_id(video_url) if video_url else ""
    if not aweme_hint:
        aweme_hint = await _resolve_aweme_id_at_index(ctx, video_index)

    if aweme_hint and await _open_feed_via_modal_id(ctx, aweme_hint):
        if await _wait_search_feed_overlay(ctx, aweme_hint=aweme_hint, max_sec=5.0):
            note = f"modal_open index={video_index + 1} aweme={aweme_hint[:12]}"
            ctx.phase_log.append(f"ITEM_CLICK {note}")
            await _report_step(
                ctx,
                f"步骤 4/7：打开第 {video_index + 1} 个视频",
                sub="Feed 浮层 · modal_id",
                log=False,
            )
            return True, note

    if not await _ensure_search_item_index(ctx, video_index):
        return False, f"搜索列表第 {video_index + 1} 项不可用（滚动后仍不足）"

    clicked, click_note = await _click_search_result_item(ctx, video_index, skip_back=True)
    if not clicked:
        await _report_step(ctx, f"视频 {video_index + 1}：点击失败", sub=click_note, log=False)
        return False, f"未能点击第 {video_index + 1} 个视频；{click_note}"

    snap_after = await classify_douyin_page(ctx.page)
    ctx.phase_log.append(
        f"PAGE_AFTER_CLICK phase={snap_after.get('phase')} feed={snap_after.get('feed_visible')} "
        f"list={snap_after.get('list_visible')} url={str(ctx.page.url or '')[:96]}"
    )
    if snap_after.get("on_video"):
        aweme_recover = ""
        with contextlib.suppress(ValueError):
            aweme_recover = _extract_aweme_id(video_url) if video_url else ""
        if not aweme_recover:
            aweme_recover = await _resolve_aweme_id_at_index(ctx, video_index)
        if aweme_recover and await _open_feed_via_modal_id(ctx, aweme_recover):
            if await _wait_search_feed_overlay(ctx, aweme_hint=aweme_recover, max_sec=5.0):
                ctx.phase_log.append(f"RECOVERED feed_overlay from video_page aweme={aweme_recover[:12]}")
            else:
                await _report_step(ctx, "详情页未就绪", sub="误入 /video/ 页且 modal 恢复失败", log=False)
                return False, f"误入独立视频详情页，Feed 浮层恢复失败；{click_note}"
        else:
            await _report_step(ctx, "详情页未就绪", sub="误入 /video/ 独立详情页", log=False)
            return False, f"误入独立视频详情页（评论在视频下方），请重试；{click_note}"

    if not await _wait_search_feed_overlay(ctx, aweme_hint=await _resolve_aweme_id_at_index(ctx, video_index), max_sec=4.0):
        await _report_step(ctx, "Feed 浮层未就绪", sub=await _page_phase_note(ctx.page), log=False)
        return False, f"进详情后 Feed 浮层未就绪；{await _page_phase_note(ctx.page)}"

    ctx.phase_log.append(f"ITEM_CLICK index={video_index} {click_note}")
    await _report_step(
        ctx,
        f"步骤 4/7：点击第 {video_index + 1} 个视频",
        sub=click_note[:48] if click_note else "进入详情…",
        log=False,
    )
    return True, click_note


async def _ensure_search_item_index(ctx: DouyinUiSession, index: int) -> bool:
    """列表 item 不足时滚动加载，直到 index 可点或达到尝试上限。"""
    page = ctx.page
    aweme_ids = list(ctx.state.get("search_aweme_ids") or [])

    async def _index_ready() -> bool:
        ids = list(ctx.state.get("search_aweme_ids") or [])
        if len(ids) > index:
            return True
        if await _count_search_posters(page) > index:
            return True
        synced = await _sync_search_aweme_ids_from_dom(ctx)
        return len(synced) > index

    if await _index_ready():
        return True
    if not await search_list_visible(page):
        return len(list(ctx.state.get("search_aweme_ids") or [])) > index

    max_scroll_attempts = max(6, min(16, (index + 4) // 2 + 2))
    for _ in range(max_scroll_attempts):
        if await _index_ready():
            return True
        if not await search_list_visible(page):
            break
        await scroll_search_results_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        await asyncio.sleep(random.uniform(0.5, 1.0))
        aweme_ids = list(ctx.state.get("search_aweme_ids") or [])

    return await _index_ready()


def _resolve_lead_aweme_id(lead: PreciseLeadRecord) -> str:
    aid = str(lead.aweme_id or "").strip()
    if aid:
        return aid
    url = str(lead.video_url or "").strip()
    if not url:
        return ""
    with contextlib.suppress(ValueError):
        return _extract_aweme_id(url)
    part = url.rstrip("/").split("/")[-1]
    return part if re.fullmatch(r"\d{8,22}", part) else ""


def _persist_precise_lead(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
) -> tuple[int, str | None]:
    """单条精准线索入库，返回 (写入行数, 失败原因)。"""
    if not lead.comment_id:
        return 0, "missing comment_id"
    aweme_id = _resolve_lead_aweme_id(lead)
    if not aweme_id:
        return 0, "missing aweme_id/content_id"
    if aweme_id != lead.aweme_id:
        lead.aweme_id = aweme_id
    raw = dict(lead.raw_comment) if isinstance(lead.raw_comment, dict) else {}
    raw.setdefault("comment_id", lead.comment_id)
    raw.setdefault("comment", lead.comment_text)
    raw.setdefault("username", lead.username)
    block = {
        "platform": PLATFORM,
        "aweme_id": aweme_id,
        "video_url": lead.video_url or f"https://www.douyin.com/video/{aweme_id}",
        "comments": [raw],
        "keyword_context": {
            "keyword": config.keyword or _result_subject(config),
            "capture_mode": capture_method_for_mode(config.acquisition_mode),
            "status": "precise",
        },
    }
    jid = str(config.source_job_id or "").strip()
    try:
        saved = persist_crawl_skill_result(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=PLATFORM,
            skill_result={"results": [block]},
            source_job_id=jid or None,
            source_keyword=config.keyword,
        )
        if saved <= 0:
            return 0, "db merge returned 0 (duplicate or empty payload)"
        return saved, None
    except Exception as exc:
        return 0, str(exc)


def _persist_lead_immediate(
    *,
    db_session: Session | None,
    settings: Settings,
    tenant_id: str,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
    phase_log: list[str] | None = None,
) -> int:
    """命中后立即入库；失败写入 phase_log / logger。"""
    if not config.persist_to_db or db_session is None:
        return 0
    if lead.persisted:
        return 0
    saved, err = _persist_precise_lead(
        db_session,
        settings,
        tenant_id=tenant_id,
        lead=lead,
        config=config,
    )
    cid_short = (lead.comment_id or "")[:8]
    if saved > 0:
        lead.persisted = True
        lead.persist_error = ""
        msg = f"SAVED lead cid={cid_short} rows={saved} user=@{lead.username}"
        _logger.info(msg)
    else:
        lead.persist_error = err or "unknown"
        msg = f"PERSIST_FAIL cid={cid_short} user=@{lead.username} reason={lead.persist_error}"
        _logger.warning(msg)
    if phase_log is not None:
        phase_log.append(msg)
    return saved


def _flush_unpersisted_leads(
    *,
    db_session: Session | None,
    settings: Settings,
    tenant_id: str,
    config: StandaloneKeywordBrowseConfig,
    leads: list[PreciseLeadRecord],
    phase_log: list[str] | None = None,
) -> int:
    """补入库尚未 persisted 的线索（异常/中断 salvage）。"""
    total = 0
    pending = [lead for lead in leads if not lead.persisted]
    if not pending:
        return 0
    for lead in pending:
        total += _persist_lead_immediate(
            db_session=db_session,
            settings=settings,
            tenant_id=tenant_id,
            lead=lead,
            config=config,
            phase_log=phase_log,
        )
    if total and phase_log is not None:
        phase_log.append(f"SALVAGE_FLUSH pending={len(pending)} rows={total}")
    return total


def _apply_partial_salvage(
    result: StandaloneKeywordBrowseResult,
    all_leads: list[PreciseLeadRecord],
    *,
    exc: BaseException | None,
    ctx: DouyinUiSession,
    config: StandaloneKeywordBrowseConfig,
    db_session: Session | None,
    dedupe_stats: dict[str, int],
    target: int,
    error_code: str = "E_GUARD",
) -> None:
    flushed = _flush_unpersisted_leads(
        db_session=db_session,
        settings=ctx.settings,
        tenant_id=ctx.tenant_id,
        config=config,
        leads=all_leads,
        phase_log=ctx.phase_log,
    )
    result.precise_leads = all_leads
    result.comments_persisted = sum(1 for lead in all_leads if lead.persisted)
    result.duplicates_skipped = int(dedupe_stats.get("duplicates_skipped") or 0)
    result.target_reached = len(all_leads) >= target
    result.ok = bool(all_leads) or result.videos_processed > 0
    result.phase_log = list(ctx.phase_log)
    msg = str(exc).strip() if exc else ""
    if all_leads:
        parts = [f"已保留 {len(all_leads)} 条精准线索"]
        if flushed:
            parts.append(f"补入库 {flushed} 条")
        if msg:
            parts.insert(0, msg)
        result.diagnostic = "；".join(parts) + "，可继续续扫"
    else:
        result.error = error_code
        result.diagnostic = msg or error_code


async def _close_video_browse(ctx: DouyinUiSession) -> None:
    """关闭当前视频浮层/侧栏，回到可点下一个视频的状态。"""
    page = ctx.page
    for _ in range(2):
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        await asyncio.sleep(0.15)
    await close_feed_detail_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
    ctx.state["feed_mode"] = False
    await human_delay(page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")


async def _run_lead_outreach_safe(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    action: OutreachAction,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
) -> dict[str, Any]:
    """触达失败（含登录/Cookie 门禁）不中断整段浏览，仅跳过本条触达。"""
    try:
        if config.test_all_outreach:
            return await _execute_all_outreach_for_lead(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                lead=lead,
                config=config,
            )
        return await _execute_outreach_if_needed(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            action=action,
            lead=lead,
            config=config,
        )
    except HumanBrowseGuardError as exc:
        return {"ok": False, "error": str(exc), "guard": True, "action": str(action or "skip")}
    except Exception as exc:
        _logger.warning("outreach failed cid=%s: %s", (lead.comment_id or "")[:12], exc)
        return {"ok": False, "error": str(exc), "action": str(action or "skip")}


def _parent_comment_id_from_lead(lead: PreciseLeadRecord) -> str:
    raw = lead.raw_comment if isinstance(lead.raw_comment, dict) else {}
    return str(raw.get("parent_comment_id") or "").strip()


async def _fallback_reply_from_warm_failure(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
    failed_action: OutreachAction,
    warm_result: dict[str, Any],
) -> dict[str, Any]:
    """warm_outreach 关注/私信失败时，回退为评论回复（与旧 Supervisor 行为一致）。"""
    if not config.reply_text:
        return {**warm_result, "action": str(failed_action or "skip")}
    from app.services.social_roam.human.douyin.actions import human_reply_comment

    parent_cid = _parent_comment_id_from_lead(lead)
    reply_result = await human_reply_comment(
        page,
        settings,
        tenant_id=tenant_id,
        content_url=lead.video_url,
        reply_text=config.reply_text,
        comment_id=lead.comment_id,
        comment_text=lead.comment_text,
        parent_comment_id=parent_cid,
    )
    if reply_result.get("ok"):
        return {**reply_result, "action": "reply", "fallback_from": failed_action}
    return {
        **warm_result,
        "action": str(failed_action or "skip"),
        "reply_fallback": reply_result,
    }


async def _warm_outreach_for_lead(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
    do_follow: bool,
    do_dm: bool,
) -> dict[str, Any]:
    """私信/关注走与 Supervisor Skill 相同的 warm_outreach 链路。"""
    from app.services.social_roam.human.douyin.warm_outreach_profile import (
        warm_outreach_follow_dm_from_comment,
    )

    return await warm_outreach_follow_dm_from_comment(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        content_url=lead.video_url,
        comment_id=lead.comment_id,
        comment_text=lead.comment_text,
        sec_uid=lead.sec_uid,
        user_id=lead.user_id,
        nickname=lead.username,
        message=config.dm_text or "",
        do_follow=do_follow,
        do_dm=do_dm,
    )


async def _execute_all_outreach_for_lead(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
) -> dict[str, Any]:
    """命中精准线索后依次测试：回复 → 关注 → 私信（关注/私信走 warm_outreach）。"""
    from app.services.social_roam.human.douyin.actions import human_reply_comment

    results: dict[str, Any] = {}
    policy = config.action_policy or {}
    interval = lambda: random_interval_sec(
        int(policy.get("interval_min_sec") or 8),
        int(policy.get("interval_max_sec") or 18),
    )

    parent_cid = _parent_comment_id_from_lead(lead)

    if config.reply_text:
        await set_page_step_hint(
            page,
            "触达：回复评论",
            sub=(lead.username or lead.comment_text or "")[:40],
            title="Huoke · 抖音浏览",
        )
        results["reply"] = await human_reply_comment(
            page,
            settings,
            tenant_id=tenant_id,
            content_url=lead.video_url,
            reply_text=config.reply_text,
            comment_id=lead.comment_id,
            comment_text=lead.comment_text,
            parent_comment_id=parent_cid,
        )
        await asyncio.sleep(interval())

    if lead.sec_uid:
        await set_page_step_hint(
            page,
            "触达：warm 进主页",
            sub=f"@{lead.username or lead.sec_uid[:16]}",
            title="Huoke · 抖音浏览",
        )
        warm = await _warm_outreach_for_lead(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            lead=lead,
            config=config,
            do_follow=True,
            do_dm=bool(config.dm_text),
        )
        results["warm_outreach"] = warm
        if warm.get("follow") is not None:
            results["follow"] = warm.get("follow")
        if warm.get("dm") is not None:
            results["dm"] = warm.get("dm")

    results["ok"] = any(
        isinstance(v, dict) and v.get("ok") for k, v in results.items() if k in {"reply", "follow", "dm"}
    )
    return results


def _comment_id_from_row(row: dict[str, Any]) -> str:
    return str(row.get("comment_id") or "").strip()


def _take_unique_comments(
    rows: list[dict[str, Any]],
    seen_comment_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """按 comment_id 去重：跨视频、跨滚动轮次均不重复处理。"""
    unique: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        cid = _comment_id_from_row(row)
        if not cid:
            continue
        if cid in seen_comment_ids:
            skipped += 1
            continue
        seen_comment_ids.add(cid)
        unique.append(row)
    return unique, skipped


def _build_ui_session(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    config: StandaloneKeywordBrowseConfig,
) -> DouyinUiSession:
    raw: dict[str, Any] = {
        "keyword": str(config.keyword or _result_subject(config) or "manual"),
        "content_limit": max(1, int(config.content_limit)),
        "days": config.video_publish_days if config.video_publish_days is not None else config.days,
        "ui_search_only": _is_keyword_mode(config),
        "inline_ui_outreach": False,
        "platform_options": {"entry": "jingxuan"} if _is_keyword_mode(config) else {"entry": "home"},
    }
    if config.region:
        raw["region"] = config.region
    if _is_manual_mode(config):
        raw["acquisition_mode"] = config.acquisition_mode
        if config.video_url:
            raw["video_url"] = config.video_url
        if config.profile_url:
            raw["profile_url"] = config.profile_url
    params = parse_ui_flow_params(raw, platform="douyin")
    return DouyinUiSession(
        settings=settings,
        tenant_id=tenant_id,
        account_id=account_id,
        params=params,
        page=page,
    )


async def _emit_crawl_progress(
    ctx: DouyinUiSession,
    message: str,
    *,
    sub: str = "",
    force: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """向 Supervisor / 任务 job 推送中间进度（节流，避免频繁写库）。"""
    cb = ctx.state.get("_on_progress")
    if not callable(cb):
        return
    now = asyncio.get_running_loop().time()
    last = float(ctx.state.get("_progress_last_emit") or 0.0)
    key = f"{message}|{sub}"
    if not force and now - last < 2.0 and ctx.state.get("_progress_last_key") == key:
        return
    ctx.state["_progress_last_emit"] = now
    ctx.state["_progress_last_key"] = key
    payload: dict[str, Any] = {
        "phase": message,
        "sub": sub,
        "action": "crawl_keyword",
    }
    if extra:
        payload.update(extra)
    maybe = cb("crawl_progress", payload)
    if asyncio.iscoroutine(maybe):
        await maybe


async def _report_step(
    ctx: DouyinUiSession,
    message: str,
    *,
    sub: str = "",
    log: bool = True,
    progress_force: bool = False,
    progress_extra: dict[str, Any] | None = None,
    detail: str | None = None,
) -> None:
    """右上角步骤条 + phase_log + 任务进度同步更新。"""
    if log:
        line = message if not sub else f"{message} | {sub}"
        ctx.phase_log.append(line[:240])
    await set_page_step_hint(ctx.page, message, sub=sub, title="Huoke · 抖音浏览", detail=detail)
    await _emit_crawl_progress(
        ctx,
        message,
        sub=sub,
        force=progress_force,
        extra=progress_extra,
    )


async def _sleep_with_overlay(
    ctx: DouyinUiSession,
    seconds: float,
    message: str,
    sub: str,
) -> None:
    """长等待期间每秒刷新 overlay，避免看起来像卡住。"""
    if seconds <= 0:
        return
    end = asyncio.get_running_loop().time() + seconds
    while True:
        remain = end - asyncio.get_running_loop().time()
        if remain <= 0:
            break
        remain_int = max(1, int(remain + 0.99))
        await set_page_step_hint(
            ctx.page,
            message,
            sub=f"{sub} · 还需 {remain_int}s",
            title="Huoke · 抖音浏览",
        )
        await asyncio.sleep(min(1.0, remain))


async def _wait_captcha_if_needed(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    headless: bool = False,
    max_wait_sec: int = 300,
) -> None:
    """可见浏览器：遇验证码时等待人工完成，而非立即失败。"""
    if not await is_captcha_page(page):
        return
    await set_page_step_hint(page, "等待验证码", sub="请在浏览器中完成人机验证", title="Huoke · 抖音浏览")
    if headless:
        raise HumanBrowseGuardError("命中验证码中间页，请用有头浏览器完成验证后重试")
    deadline = asyncio.get_running_loop().time() + max(30, int(max_wait_sec))
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(2.5)
        if not await is_captcha_page(page):
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
            return
    raise HumanBrowseGuardError("验证码等待超时，请在浏览器中完成人机验证后重试")


async def _attempt_search_reuse(
    ctx: DouyinUiSession,
    config: StandaloneKeywordBrowseConfig,
) -> tuple[bool, str]:
    """续扫/继续浏览：已在搜索列表则跳过重搜与回精选。"""
    if not _is_keyword_mode(config) or not ctx.state.get("reuse_search_session"):
        return False, ""

    page = ctx.page
    if not _on_search_results_url(page.url or "") or await feed_overlay_visible(page):
        if not await _back_to_search_list(ctx):
            if not _on_search_results_url(page.url or ""):
                return False, ""

    reused = await reuse_search_results_if_ready(
        ctx,
        limit=max(1, int(config.content_limit)),
    )
    if reused is None:
        return False, ""

    publish_days = _publish_days_for_config(config)
    api_days_fallback = _needs_ui_publish_filter(ctx) and not ctx.state.get("search_filter_verified")
    aweme_ids = _sync_search_aweme_ids_from_api(
        ctx,
        {},
        days=publish_days,
        api_days_fallback=api_days_fallback,
    )
    if not aweme_ids:
        aweme_ids = await _sync_search_aweme_ids_from_dom(ctx)
        if aweme_ids:
            ctx.state["search_aweme_ids"] = aweme_ids

    filter_suffix = _filter_diagnostic_suffix(ctx)
    diag = (reused.diagnostic or "复用搜索页") + filter_suffix
    ctx.phase_log.append(f"SEARCH_REUSE {diag[:180]} url={str(page.url or '')[:96]}")
    filter_label = _publish_filter_ui_label(config)
    sub = f"「{config.keyword}」"
    if filter_label:
        sub += f" · 发布时间 {filter_label}"
    await _report_step(
        ctx,
        "复用搜索列表",
        sub=f"{sub} · 跳过重新搜索",
        log=False,
        progress_force=True,
    )
    return True, diag


async def _attempt_resume_saved_search(
    ctx: DouyinUiSession,
    config: StandaloneKeywordBrowseConfig,
    *,
    page: Page,
    settings: Settings,
    tenant_id: str,
    account_id: str,
    store: DouyinSessionStore,
    headless: bool = False,
    stable_session: Any | None = None,
) -> tuple[bool, str]:
    """续扫：stable 会话内 goto 已保存搜索页，跳过重灌 Cookie + 重搜。"""
    resume_url = str(config.resume_search_url or "").strip()
    start_idx = max(0, int(config.start_video_index or 0))
    if not resume_url or start_idx <= 0 or not _is_keyword_mode(config):
        return False, ""
    if "/search/" not in resume_url.lower():
        return False, ""

    ctx.state["search_url"] = resume_url
    ctx.state.setdefault("search_submitted", True)

    if stable_session is not None:
        with contextlib.suppress(Exception):
            await page.bring_to_front()

    if await feed_overlay_visible(page):
        await _back_to_search_list(ctx)

    if not _on_search_results_url(page.url or ""):
        try:
            await page.goto(resume_url, wait_until="domcontentloaded", timeout=45000)
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
        except Exception as exc:
            ctx.phase_log.append(f"RESUME_SEARCH goto failed={str(exc)[:120]}")
            return False, str(exc)

    await _wait_captcha_if_needed(page, settings, tenant_id=tenant_id, headless=headless)
    await assert_douyin_human_ready(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        store=store,
        stage="home",
        goto_home=False,
    )

    reused, reuse_diag = await _attempt_search_reuse(ctx, config)
    if reused:
        filter_label = _publish_filter_ui_label(config)
        sub = f"从第 {start_idx + 1} 个视频继续"
        if filter_label:
            sub += f" · 发布时间 {filter_label}"
        await _report_step(
            ctx,
            "续扫：恢复搜索列表",
            sub=f"{sub} · 跳过重新搜索",
            log=False,
            progress_force=True,
            progress_extra={"start_video_index": start_idx, "resume_search_url": resume_url[:120]},
        )
        return True, reuse_diag or "续扫：恢复已保存搜索页"

    if _on_search_results_url(page.url or "") and await page_has_search_posters(page):
        ctx.state["search_url"] = page.url or resume_url
        diag = f"续扫：已打开搜索页 url={str(page.url or '')[:96]}"
        ctx.phase_log.append(diag)
        await _report_step(
            ctx,
            "续扫：恢复搜索列表",
            sub=f"从第 {start_idx + 1} 个视频继续",
            log=False,
            progress_force=True,
            progress_extra={"start_video_index": start_idx},
        )
        return True, diag

    return False, ""


async def _open_douyin_home(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    store: DouyinSessionStore,
    headless: bool = False,
    stable_session: Any | None = None,
    entry_url: str = DOUYIN_ENTRY_URL,
    step_title: str = "步骤 1/7：打开抖音首页",
    reuse_search: bool = False,
    search_ctx: DouyinUiSession | None = None,
) -> None:
    """步骤 1：打开抖音首页并等待加载完成。

    稳定基座模式下若当前标签已在抖音首页，则跳过 goto，复用桌面已登录会话。
    关键词模式默认从精选页进入，与 skill-flow 搜索框路径一致。
    """
    from app.services.browser_workbench import is_douyin_home_like, should_skip_stable_goto
    from app.services.ui_flow.platforms.douyin.search_ui import page_ready_for_search_reuse

    await set_page_step_hint(page, step_title, title="Huoke · 抖音浏览")
    if reuse_search and search_ctx is not None:
        if await feed_overlay_visible(page):
            if await _back_to_search_list(search_ctx):
                page = search_ctx.page
        if await page_ready_for_search_reuse(search_ctx):
            await set_page_step_hint(
                page,
                step_title.replace("打开", "复用"),
                sub="已在搜索列表，跳过回精选",
                title="Huoke · 抖音浏览",
            )
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
            await _wait_captcha_if_needed(page, settings, tenant_id=tenant_id, headless=headless)
            await assert_douyin_human_ready(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                store=store,
                stage="home",
                goto_home=False,
            )
            return

    skip_goto = False
    if stable_session is not None:
        skip, reason = should_skip_stable_goto(stable_session, entry_url)
        if skip:
            skip_goto = True
        elif is_douyin_home_like(page.url or ""):
            skip_goto = True
            reason = "already_on_home"
        if skip_goto:
            await set_page_step_hint(page, step_title.replace("打开", "复用"), sub=reason or "")
            await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
            await _wait_captcha_if_needed(page, settings, tenant_id=tenant_id, headless=headless)
            await assert_douyin_human_ready(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                store=store,
                stage="home",
                goto_home=False,
            )
            return

    await page.goto(entry_url, wait_until="domcontentloaded", timeout=60000)
    await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    await _wait_captcha_if_needed(page, settings, tenant_id=tenant_id, headless=headless)
    await assert_douyin_human_ready(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        store=store,
        stage="home",
        goto_home=False,
    )


async def _run_search_phase(
    ctx: DouyinUiSession,
    *,
    config: StandaloneKeywordBrowseConfig,
) -> tuple[bool, str]:
    """步骤 2–3：精选页搜索框输入 + 发布时间筛选（与 skill-flow search_ui 对齐）。

    成功判定：搜索页 URL + 列表已展示（DOM 或 search API），不依赖 video_urls。
    """
    page = ctx.page
    publish_days = _publish_days_for_config(config)
    filter_label = _publish_filter_ui_label(config)
    search_sub = f"「{ctx.params.keyword}」"
    if filter_label:
        search_sub += f" · 发布时间 {filter_label}"

    await _report_step(
        ctx,
        "步骤 2/7：搜索关键词",
        sub=search_sub,
        log=True,
    )

    reused, reuse_diag = await _attempt_search_reuse(ctx, config)
    if reused:
        return True, reuse_diag

    prepare = await run_prepare(ctx)
    if not prepare.ok:
        diag = prepare.diagnostic or prepare.error or "精选页搜索框未就绪"
        ctx.phase_log.append(f"SEARCH_PREP failed={diag[:160]}")
        return False, diag

    api_items: dict[str, dict] = {}
    search_flags: dict[str, Any] = {}

    async def on_search_response(resp) -> None:
        if not is_search_result_api(str(resp.url or "")) or resp.status >= 400:
            return
        try:
            data = await resp.json()
        except Exception:
            return
        need = search_api_min_items(ctx.params.content_limit)
        outcome = analyze_search_api_response(data, min_items=need)
        mark_search_api_flags(search_flags, outcome)
        if outcome.ready:
            ctx.state["search_api_complete"] = True
            ctx.state["search_api_complete_reason"] = outcome.reason
        for row in extract_aweme_items_from_json(data):
            api_items.setdefault(str(row.get("aweme_id") or ""), row)
        if len(api_items) >= need:
            search_flags["api_complete"] = True
            search_flags["api_complete_reason"] = f"items={len(api_items)}"
            ctx.state["search_api_complete"] = True
            ctx.state["search_api_complete_reason"] = search_flags["api_complete_reason"]

    page.on("response", on_search_response)
    try:
        await _report_step(ctx, "正在输入搜索词并提交…", log=False)
        search_result = await run_search(ctx)
        _log_search_filter_state(ctx)

        needs_filter = _needs_ui_publish_filter(ctx)
        if needs_filter and not ctx.state.get("search_filter_applied"):
            ctx.phase_log.append("SEARCH_FILTER retry")
            retry_label = await apply_ui_publish_time_filter(ctx)
            if retry_label:
                ctx.state["search_filter_applied"] = retry_label
                api_items.clear()
                search_flags.pop("api_complete", None)
                search_flags.pop("api_complete_reason", None)
                for _ in range(16):
                    if api_items:
                        break
                    await asyncio.sleep(0.35)
            _log_search_filter_state(ctx)

        for _ in range(12):
            if api_items:
                break
            await asyncio.sleep(0.25)
        if search_result.ok and isinstance(search_result.data, dict):
            result_ids = search_result.data.get("search_aweme_ids") or []
            if result_ids:
                ctx.state["search_aweme_ids"] = [str(i) for i in result_ids if str(i)]
        api_days_fallback = needs_filter and not ctx.state.get("search_filter_verified")
        aweme_ids = _sync_search_aweme_ids_from_api(
            ctx,
            api_items,
            days=publish_days,
            api_days_fallback=api_days_fallback,
        )
        list_ready = await _is_search_list_ready(page, api_items, ctx=ctx)
        filter_suffix = _filter_diagnostic_suffix(ctx)

        if search_result.ok:
            if not aweme_ids:
                aweme_ids = _sync_search_aweme_ids_from_api(
                    ctx,
                    api_items,
                    days=publish_days,
                    api_days_fallback=api_days_fallback,
                )
            ctx.state["search_ready"] = True
            ctx.state.setdefault("search_url", page.url)
            ctx.state["search_poster_mode"] = True
            api_count = len(api_items)
            api_reason = ctx.state.get("search_api_complete_reason") or search_flags.get("api_complete_reason")
            diag = (search_result.diagnostic or "搜索完成") + filter_suffix
            if api_count:
                diag += f"；api_videos={api_count}"
            if api_reason:
                diag += f"；api_status={api_reason}"
            filter_sub = filter_suffix.lstrip("；") or f"已识别 {api_count or len(aweme_ids)} 个视频"
            if api_reason and filter_sub == filter_suffix.lstrip("；"):
                filter_sub += f" · {api_reason}"
            await _report_step(
                ctx,
                "步骤 3/7：搜索完成",
                sub=filter_sub if filter_suffix else (
                    f"已识别 {api_count or len(aweme_ids)} 个视频"
                    + (f" · {api_reason}" if api_reason else "")
                ),
                log=True,
            )
            return True, diag

        if list_ready:
            ctx.state["search_ready"] = True
            ctx.state["search_url"] = ctx.state.get("search_url") or page.url
            ctx.state["search_poster_mode"] = True
            ctx.phase_log.append(
                f"SEARCH_FALLBACK list_visible api={len(api_items)} url={page.url}{filter_suffix}"
            )
            await release_searchbar_focus(page)
            await _report_step(
                ctx,
                "步骤 3/7：列表已展示",
                sub=(
                    f"API {len(api_items)} 条"
                    + (
                        f" · {ctx.state.get('search_api_complete_reason')}"
                        if ctx.state.get("search_api_complete_reason")
                        else ""
                    )
                    + filter_suffix
                    + "，准备点击视频"
                ),
                log=True,
            )
            return True, (
                f"列表已展示，按 DOM 顺序点击（api={len(api_items)}）{filter_suffix}；"
                f"原判定={search_result.error or search_result.diagnostic or 'unknown'}"
            )

        return False, (search_result.diagnostic or search_result.error or "搜索失败") + filter_suffix
    finally:
        try:
            page.remove_listener("response", on_search_response)
        except Exception:
            pass


def _keyword_matches_comment(config: StandaloneKeywordBrowseConfig, text: str) -> bool:
    comment = (text or "").strip()
    if len(comment) < max(1, int(config.min_comment_length)):
        return False
    keywords = list(config.match_keywords)
    if not keywords and str(config.keyword or "").strip():
        keywords = [str(config.keyword).strip()]
    if not keywords:
        return len(comment) >= max(1, int(config.min_comment_length))
    return _match_comment(comment, keywords, config.exclude_keywords)


async def _evaluate_comments_batch(
    rows: list[dict[str, Any]],
    config: StandaloneKeywordBrowseConfig,
    settings: Settings,
) -> dict[str, dict[str, Any]]:
    """评估评论：默认关键词匹配；可选 LLM 意图评估。"""
    out: dict[str, dict[str, Any]] = {}
    if config.use_llm_eval and config.eval_spec and config.task_brief:
        from app.services.lead_evaluation_service import (
            accept_evaluation_result,
            evaluate_comments_batch,
            is_precise_lead,
        )

        classified = await evaluate_comments_batch(
            rows,
            config.eval_spec,
            config.task_brief,
            settings=settings,
        )
        for cid, result in classified.items():
            if accept_evaluation_result(result, config.eval_spec) and is_precise_lead(result, config.eval_spec):
                out[cid] = result
        return out

    for row in rows:
        cid = str(row.get("comment_id") or "").strip()
        text = str(row.get("comment") or "").strip()
        if not cid or not _keyword_matches_comment(config, text):
            continue
        out[cid] = {
            "comment_id": cid,
            "is_lead": True,
            "score": 0.85,
            "reason": "关键词匹配",
            "worth_outreach": True,
        }
    return out


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


async def _decide_outreach_action(
    config: StandaloneKeywordBrowseConfig,
    stats: dict[str, int],
) -> OutreachAction:
    policy = config.action_policy or {}
    action = choose_outreach_action(
        comment_ratio=int(policy.get("comment_ratio") or 50),
        dm_ratio=int(policy.get("dm_ratio") or 30),
        follow_ratio=int(policy.get("follow_ratio") or 20),
    )
    if action == "reply" and stats.get("replies", 0) >= int(policy.get("max_replies") or 9999):
        action = "dm"
    if action == "dm" and stats.get("dms", 0) >= int(policy.get("max_dms") or 9999):
        action = "follow"
    if action == "follow" and stats.get("follows", 0) >= int(policy.get("max_follows") or 9999):
        action = "skip"
    return action


async def _execute_outreach_if_needed(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    action: OutreachAction,
    lead: PreciseLeadRecord,
    config: StandaloneKeywordBrowseConfig,
) -> dict[str, Any]:
    if not config.execute_outreach or action == "skip":
        return {"ok": False, "skipped": True, "action": action}

    from app.services.social_roam.human.douyin.actions import human_reply_comment

    parent_cid = _parent_comment_id_from_lead(lead)

    if action == "reply" and config.reply_text:
        return await human_reply_comment(
            page,
            settings,
            tenant_id=tenant_id,
            content_url=lead.video_url,
            reply_text=config.reply_text,
            comment_id=lead.comment_id,
            comment_text=lead.comment_text,
            parent_comment_id=parent_cid,
        )
    if action in {"follow", "dm"} and lead.sec_uid:
        do_follow = action == "follow"
        do_dm = action == "dm" and bool(config.dm_text)
        if action == "dm" and not config.dm_text:
            return {"ok": False, "skipped": True, "action": action, "reason": "缺少私信文案"}

        hint = "触达：warm 进主页点关注" if do_follow else "触达：warm 进主页点私信"
        await set_page_step_hint(
            page,
            hint,
            sub=f"@{lead.username or lead.sec_uid[:16]}",
            title="Huoke · 抖音浏览",
        )
        warm = await _warm_outreach_for_lead(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            lead=lead,
            config=config,
            do_follow=do_follow,
            do_dm=do_dm,
        )
        if action == "follow":
            follow = warm.get("follow") if isinstance(warm.get("follow"), dict) else {}
            ok = bool(warm.get("ok")) and bool(follow.get("ok"))
            if not ok:
                err = str(warm.get("error") or follow.get("error") or "关注失败")[:80]
                await set_page_step_hint(page, "触达失败：关注", sub=err, title="Huoke · 抖音浏览")
                return await _fallback_reply_from_warm_failure(
                    page,
                    settings,
                    tenant_id=tenant_id,
                    lead=lead,
                    config=config,
                    failed_action=action,
                    warm_result={**warm, "action": action},
                )
            return {**follow, "ok": True, "action": "follow", "profile_url": warm.get("profile_url")}
        dm = warm.get("dm") if isinstance(warm.get("dm"), dict) else {}
        ok = bool(warm.get("ok")) and bool(dm.get("ok"))
        if not ok:
            err = str(warm.get("error") or dm.get("error") or "私信失败")[:80]
            await set_page_step_hint(page, "触达失败：私信", sub=err, title="Huoke · 抖音浏览")
            return await _fallback_reply_from_warm_failure(
                page,
                settings,
                tenant_id=tenant_id,
                lead=lead,
                config=config,
                failed_action=action,
                warm_result={**warm, "action": action},
            )
        return {**dm, "ok": True, "action": "dm", "profile_url": warm.get("profile_url")}
    return {"ok": False, "skipped": True, "action": action, "reason": "缺少触达文案或未实现"}


async def _browse_video_comments(
    ctx: DouyinUiSession,
    *,
    config: StandaloneKeywordBrowseConfig,
    video_index: int,
    video_url: str,
    seen_comment_ids: set[str],
    outreach_stats: dict[str, int],
    dedupe_stats: dict[str, int],
    db_session: Session | None = None,
    leads_before: int = 0,
) -> tuple[list[PreciseLeadRecord], int, str]:
    """步骤 5–7：单视频评论浏览、评估、保存线索。"""
    page = ctx.page
    leads: list[PreciseLeadRecord] = []
    comment_days = config.comment_days if config.comment_days is not None else config.days
    cutoff_ts = _days_cutoff_ts(comment_days)
    # 翻页不因条数上限停止，仅按有效时间窗 + 无更多分页；上限仅防极端死循环
    filter_cap = max(10_000, int(config.max_comments_per_video or 0) * 20)
    safety_max_rounds = max(120, int(config.comment_scroll_rounds or 60) * 4)
    target = max(1, int(config.target_precise_leads))

    entered, enter_note = await _enter_video_for_browse(
        ctx,
        config=config,
        video_index=video_index,
        video_url=video_url,
    )
    if not entered:
        return leads, 0, enter_note

    await _report_step(ctx, f"步骤 5/7：打开评论侧栏", sub=f"视频 {video_index + 1}", log=False)

    # 进详情后尽快点评论：短暂停留即点，避免干等 watch_seconds
    await asyncio.sleep(random.uniform(0.8, 1.6))

    if not await is_search_feed_overlay(page) and not await is_feed_detail_open(page):
        return leads, 0, f"打开评论前不在 Feed 浮层；{await _page_phase_note(page)}"

    captured_pages: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    handler = _comment_response_handler(captured_pages, seen_signatures=seen_signatures)
    page.on("response", handler)

    ctx.phase_log.append("COMMENT_OPEN start")
    sidebar_ok = await activate_comment_sidebar_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
    ctx.phase_log.append(f"COMMENT_OPEN ok={sidebar_ok} {await _page_phase_note(page)}")
    if sidebar_ok:
        await _report_step(
            ctx,
            "步骤 6/7：浏览评论",
            sub="拦截 comment/list · 评估线索",
            log=False,
        )
    else:
        await _report_step(ctx, "评论侧栏打开失败", sub="未点到评论入口", log=False)
    if not sidebar_ok:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass
        await close_feed_detail_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
        return leads, 0, "未能打开评论侧栏（未点到评论入口）"

    sort_latest_ok = await select_latest_comment_sort_on_page(page, ctx.settings, tenant_id=ctx.tenant_id)
    min_time_rounds = 1 if sort_latest_ok else 2
    await asyncio.sleep(random.uniform(0.6, 1.2))

    aweme_id = ""
    try:
        aweme_id = _extract_aweme_id(video_url or page.url)
    except ValueError:
        aweme_id = str(ctx.state.get("search_aweme_ids", [""])[video_index] if video_index < len(ctx.state.get("search_aweme_ids") or []) else "")

    stop_reason = ""
    scanned = 0

    try:
        for round_idx in range(safety_max_rounds + 1):
            if round_idx > 0 and not await _comment_sidebar_active(page):
                stop_reason = "评论侧栏已关闭，停止滚动"
                break

            comments_map, _api_total = _merge_captured_pages(captured_pages)
            filtered = _filter_comments_by_days(
                comments_map,
                cutoff_ts=cutoff_ts,
                max_comments=filter_cap,
            )
            scanned = len(comments_map)
            in_window = len(filtered)
            await _report_step(
                ctx,
                "步骤 6/7：扫描评论",
                sub=(
                    f"第 {round_idx + 1} 轮 · 累计 {scanned} 条"
                    f" · {comment_days}天内 {in_window} 条"
                    f" · 精准 {leads_before + len(leads)}/{target}"
                ),
                log=False,
            )
            last_page = _last_list_page(captured_pages)

            candidate_rows = [
                row for row in filtered if not row.get("parent_comment_id")
            ]
            new_rows, dup_skipped = _take_unique_comments(candidate_rows, seen_comment_ids)
            dedupe_stats["duplicates_skipped"] = dedupe_stats.get("duplicates_skipped", 0) + dup_skipped
            if new_rows:
                await _report_step(
                    ctx,
                    "步骤 6/7：AI 评估",
                    sub=f"第 {round_idx + 1} 轮 · {len(new_rows)} 条新评论待分析",
                    log=False,
                )
                try:
                    eval_map = await _evaluate_comments_batch(new_rows, config, ctx.settings)
                except Exception as exc:
                    ctx.phase_log.append(f"EVAL_BATCH_ERR video={video_index + 1} {str(exc)[:120]}")
                    eval_map = {}
                    await _report_step(
                        ctx,
                        "步骤 6/7：评估失败",
                        sub=f"第 {round_idx + 1} 轮 · {str(exc)[:48]} · 继续滚动",
                        log=False,
                    )
                else:
                    await _report_step(
                        ctx,
                        "步骤 6/7：评估完成",
                        sub=(
                            f"第 {round_idx + 1} 轮 · 本批 {len(new_rows)} 条"
                            f" · 精准 {len(eval_map)} 条"
                        ),
                        log=False,
                    )
                guard_hit = False
                for row in new_rows:
                    if guard_hit:
                        break
                    try:
                        cid = _comment_id_from_row(row)
                        if not cid or cid not in eval_map:
                            continue

                        eval_row = eval_map[cid]
                        action = await _decide_outreach_action(config, outreach_stats)
                        lead = PreciseLeadRecord(
                            comment_id=cid,
                            comment_text=str(row.get("comment") or ""),
                            username=str(row.get("username") or ""),
                            user_id=str(row.get("user_id") or ""),
                            sec_uid=str(row.get("sec_uid") or ""),
                            video_url=video_url or page.url,
                            aweme_id=aweme_id,
                            create_time=int(row.get("create_time") or 0),
                            match_score=float(eval_row.get("score") or 0),
                            match_reason=str(eval_row.get("reason") or ""),
                            planned_action=action,
                            raw_comment=row,
                        )

                        outreach_result: dict[str, Any] = {}
                        _persist_lead_immediate(
                            db_session=db_session,
                            settings=ctx.settings,
                            tenant_id=ctx.tenant_id,
                            lead=lead,
                            config=config,
                            phase_log=ctx.phase_log,
                        )

                        if config.execute_outreach:
                            action_labels = {"reply": "回复", "dm": "私信", "follow": "关注", "skip": "跳过"}
                            action_label = action_labels.get(str(action or "skip"), str(action or "触达"))
                            await _report_step(
                                ctx,
                                "步骤 6/7：触达线索",
                                sub=f"{action_label} @{lead.username} · {lead.comment_text[:20]}",
                                log=False,
                            )
                            outreach_result = await _run_lead_outreach_safe(
                                page,
                                ctx.settings,
                                tenant_id=ctx.tenant_id,
                                account_id=ctx.account_id,
                                action=action,
                                lead=lead,
                                config=config,
                            )
                            lead.outreach_executed = bool(outreach_result.get("ok"))
                            if config.test_all_outreach:
                                if outreach_result.get("reply", {}).get("ok"):
                                    outreach_stats["replies"] = outreach_stats.get("replies", 0) + 1
                                if outreach_result.get("dm", {}).get("ok"):
                                    outreach_stats["dms"] = outreach_stats.get("dms", 0) + 1
                                if outreach_result.get("follow", {}).get("ok"):
                                    outreach_stats["follows"] = outreach_stats.get("follows", 0) + 1
                            elif lead.outreach_executed:
                                if action == "reply":
                                    outreach_stats["replies"] = outreach_stats.get("replies", 0) + 1
                                elif action == "dm":
                                    outreach_stats["dms"] = outreach_stats.get("dms", 0) + 1
                                elif action == "follow":
                                    outreach_stats["follows"] = outreach_stats.get("follows", 0) + 1
                            lead.outreach_result = outreach_result

                        leads.append(lead)
                        ctx.phase_log.append(
                            f"LEAD video={video_index + 1} cid={cid[:8]} action={action} "
                            f"score={lead.match_score:.2f} persisted={lead.persisted}"
                        )
                        await _report_step(
                            ctx,
                            f"精准线索 {leads_before + len(leads)}/{target}",
                            sub=f"@{lead.username} · {lead.comment_text[:24]}",
                            log=False,
                            progress_force=True,
                            progress_extra={
                                "leads_qualified": leads_before + len(leads),
                                "target_leads": target,
                                "comments_scanned": scanned,
                            },
                        )

                        if leads_before + len(leads) >= target:
                            stop_reason = f"已达目标精准线索 {target} 条"
                            break

                        policy = config.action_policy or {}
                        interval = random_interval_sec(
                            int(policy.get("interval_min_sec") or 10),
                            int(policy.get("interval_max_sec") or 30),
                        )
                        await _sleep_with_overlay(
                            ctx,
                            interval,
                            "步骤 6/7：触达间隔",
                            f"@{lead.username} 后冷却",
                        )
                    except HumanBrowseGuardError as exc:
                        ctx.phase_log.append(
                            f"GUARD_LEAD video={video_index + 1} cid={_comment_id_from_row(row)[:8]} "
                            f"{str(exc)[:80]}"
                        )
                        stop_reason = f"本视频浏览中断：{exc}"
                        guard_hit = True
                    except Exception as exc:
                        cid_hint = _comment_id_from_row(row)[:8]
                        ctx.phase_log.append(f"LEAD_ERR video={video_index + 1} cid={cid_hint} {str(exc)[:100]}")
                        _logger.warning("lead processing failed cid=%s: %s", cid_hint, exc)
                if guard_hit or stop_reason:
                    break

            if stop_reason:
                break

            if await comment_list_end_marker_visible(page):
                stop_reason = "评论已全部加载（暂时没有更多评论）"
                await _report_step(
                    ctx,
                    "步骤 6/7：评论到底",
                    sub=f"第 {round_idx + 1} 轮 · 共扫描 {scanned} 条 · 切换下一视频",
                    log=False,
                )
                ctx.phase_log.append(
                    f"PAGINATION_END video={video_index + 1} scanned={scanned} reason=dom_no_more"
                )
                break

            scroll_stop = comment_scroll_stop_reason(
                cutoff_ts=cutoff_ts,
                round_idx=round_idx,
                last_page=last_page,
                captured_pages=captured_pages,
                min_scroll_before_time_stop=min_time_rounds,
                comment_days=comment_days,
            )
            if scroll_stop:
                stop_reason = scroll_stop
                if "有效窗口" in scroll_stop or "有效时间" in scroll_stop:
                    await _report_step(
                        ctx,
                        f"视频 {video_index + 1}：评论过旧",
                        sub=f"超过 {comment_days} 天窗口，切换下一个视频",
                        log=False,
                    )
                    ctx.phase_log.append(
                        f"TIME_STOP video={video_index + 1} days={comment_days} scanned={scanned}"
                    )
                else:
                    ctx.phase_log.append(
                        f"PAGINATION_END video={video_index + 1} scanned={scanned} reason={scroll_stop}"
                    )
                break

            if round_idx >= safety_max_rounds:
                stop_reason = f"已达安全滚动上限 {safety_max_rounds} 轮"
                break

            await _report_step(
                ctx,
                "步骤 6/7：向下滚动",
                sub=f"第 {round_idx + 1} 轮 · 加载更多评论…",
                log=False,
            )
            await scroll_comment_sidebar_on_page(
                page,
                ctx.settings,
                tenant_id=ctx.tenant_id,
                rounds=1,
            )
            await _sleep_with_overlay(
                ctx,
                random.uniform(1.8, 3.5),
                "步骤 6/7：等待加载",
                f"第 {round_idx + 1} 轮 · 等 comment/list",
            )
    except HumanBrowseGuardError as exc:
        stop_reason = f"本视频浏览中断：{exc}"
        ctx.phase_log.append(f"GUARD_STOP video={video_index + 1} {str(exc)[:120]}")
    except Exception as exc:
        stop_reason = f"本视频异常：{exc}"
        ctx.phase_log.append(f"VIDEO_ERR video={video_index + 1} {str(exc)[:120]}")
        _logger.warning("video comment browse error index=%s: %s", video_index + 1, exc)
    finally:
        try:
            page.remove_listener("response", handler)
        except Exception:
            pass

    _flush_unpersisted_leads(
        db_session=db_session,
        settings=ctx.settings,
        tenant_id=ctx.tenant_id,
        config=config,
        leads=leads,
        phase_log=ctx.phase_log,
    )
    with contextlib.suppress(Exception):
        await _close_video_browse(ctx)

    if not stop_reason and _newest_top_create_time_in_page(_last_list_page(captured_pages)) is None:
        stop_reason = "未拦截到评论数据"
    return leads, scanned, stop_reason or "单视频评论浏览结束"


def _serialize_leads(leads: list[PreciseLeadRecord]) -> list[dict[str, Any]]:
    return [
        {
            "comment_id": lead.comment_id,
            "comment": lead.comment_text,
            "username": lead.username,
            "user_id": lead.user_id,
            "sec_uid": lead.sec_uid,
            "video_url": lead.video_url,
            "aweme_id": lead.aweme_id,
            "create_time": lead.create_time,
            "match_score": lead.match_score,
            "match_reason": lead.match_reason,
            "planned_action": lead.planned_action,
            "outreach_executed": lead.outreach_executed,
            "outreach_result": lead.outreach_result,
            "persisted": lead.persisted,
            "persist_error": lead.persist_error,
            "status": "precise",
            "capture_method": CAPTURE_METHOD,
        }
        for lead in leads
    ]


async def _persist_session_storage(
    store: DouyinSessionStore,
    *,
    tenant_id: str,
    account_id: str,
    context: Any | None,
) -> None:
    if context is None:
        return
    try:
        await store.save_from_context(tenant_id, context, account_id)
    except Exception:
        pass


async def run_standalone_keyword_browse(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str = "default",
    config: StandaloneKeywordBrowseConfig,
    db_session: Session | None = None,
    headless: bool = False,
    stable_session: Any | None = None,
    on_progress: ProgressCallback | None = None,
) -> StandaloneKeywordBrowseResult:
    """独立抖音浏览主入口（关键词 / 单视频 / 主页，固定 UI 流程）。"""
    valid, valid_err = validate_standalone_config(config)
    if not valid:
        subject = _result_subject(config) or "standalone"
        return StandaloneKeywordBrowseResult(
            ok=False,
            keyword=subject,
            acquisition_mode=str(config.acquisition_mode or "keyword_auto"),
            source_url=_result_subject(config),
            error="E_CONFIG",
            diagnostic=valid_err,
        )

    store = DouyinSessionStore(settings)
    ctx = _build_ui_session(
        page,
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        config=config,
    )
    if on_progress is not None:
        ctx.state["_on_progress"] = on_progress
    if _is_keyword_mode(config):
        ctx.state["reuse_search_session"] = True
    subject = _result_subject(config)
    target = max(1, int(config.target_precise_leads))
    result = StandaloneKeywordBrowseResult(
        ok=False,
        keyword=subject,
        acquisition_mode=str(config.acquisition_mode or "keyword_auto"),
        source_url=subject,
    )
    seen_comment_ids: set[str] = set()
    outreach_stats: dict[str, int] = {"replies": 0, "dms": 0, "follows": 0}
    dedupe_stats: dict[str, int] = {"duplicates_skipped": 0}
    all_leads: list[PreciseLeadRecord] = []
    manual_video_urls: list[str] = []

    try:
        mode_label = {
            "keyword_auto": f"关键词「{config.keyword}」",
            "single_video": "单视频",
            "account_home": "账号主页",
        }.get(str(config.acquisition_mode), "浏览")
        await _report_step(
            ctx,
            "准备开始",
            sub=f"{mode_label} · 目标 {config.target_precise_leads} 条精准线索",
            log=False,
            progress_force=True,
            progress_extra={
                "target_leads": target,
                "start_video_index": max(0, int(config.start_video_index or 0)),
            },
        )
        ctx.phase_log.append("STEP1 open_home")
        search_phase_done = False
        if _is_keyword_mode(config):
            resumed, resume_diag = await _attempt_resume_saved_search(
                ctx,
                config,
                page=page,
                settings=settings,
                tenant_id=tenant_id,
                account_id=account_id,
                store=store,
                headless=headless,
                stable_session=stable_session,
            )
            if resumed:
                search_phase_done = True
                result.search_url = str(ctx.state.get("search_url") or config.resume_search_url or "")
                result.source_url = result.search_url
                ctx.phase_log.append(f"STEP2 search_resume {resume_diag[:120]}")

        if not search_phase_done:
            home_entry = DOUYIN_JINGXUAN_URL if _is_keyword_mode(config) else DOUYIN_ENTRY_URL
            home_title = "步骤 1/7：打开抖音精选" if _is_keyword_mode(config) else "步骤 1/7：打开抖音首页"
            await _open_douyin_home(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                store=store,
                headless=headless,
                stable_session=stable_session,
                entry_url=home_entry,
                step_title=home_title,
                reuse_search=_is_keyword_mode(config),
                search_ctx=ctx if _is_keyword_mode(config) else None,
            )

        if _is_keyword_mode(config) and not search_phase_done:
            ctx.phase_log.append("STEP2 search")
            search_ok, search_diag = await _run_search_phase(ctx, config=config)
            if not search_ok:
                result.error = "E_SEARCH"
                result.diagnostic = search_diag
                result.phase_log = list(ctx.phase_log)
                await _report_step(ctx, "搜索失败", sub=search_diag or "", log=False)
                return result

            result.search_url = str(ctx.state.get("search_url") or page.url)
            result.source_url = result.search_url
            ctx.phase_log.append(f"STEP3 search_ok url={result.search_url}")

        if _is_keyword_mode(config):
            list_prepared = await _prepare_search_list_for_browse(ctx)
            poster_n = await _count_search_posters(page)
            aweme_n = len(ctx.state.get("search_aweme_ids") or [])
            ctx.phase_log.append(
                f"STEP3b list_prepared={list_prepared} posters={poster_n} aweme_ids={aweme_n} "
                f"url={str(page.url or '')[:96]}"
            )
            if not list_prepared:
                result.error = "E_NO_LIST"
                result.diagnostic = (
                    f"搜索完成但列表不可点（海报={poster_n}，api_aweme={aweme_n}）；"
                    f"识别规则：需 search URL + (API 有数据 或 DOM 海报>0 或 search_aweme_ids)；"
                    f"url={page.url}"
                )
                result.phase_log = list(ctx.phase_log)
                await _report_step(ctx, "列表未就绪", sub=result.diagnostic, log=False)
                return result
        else:
            ctx.phase_log.append(f"STEP2 manual mode={config.acquisition_mode}")
            manual_ok, manual_diag, manual_video_urls = await _prepare_manual_video_queue(
                ctx,
                config,
                store,
            )
            if not manual_ok:
                result.error = "E_MANUAL_PREPARE"
                result.diagnostic = manual_diag
                result.phase_log = list(ctx.phase_log)
                await _report_step(ctx, "手动获客准备失败", sub=manual_diag or "", log=False)
                return result
            result.source_url = str(config.video_url or config.profile_url or subject)
            if manual_diag:
                ctx.phase_log.append(f"STEP2b manual_note={manual_diag[:120]}")

        batch_limit = max(1, int(config.max_videos_to_browse))
        start_video_index = max(0, int(config.start_video_index or 0))
        batch_end = start_video_index + batch_limit
        aweme_ids = list(ctx.state.get("search_aweme_ids") or [])
        video_index = start_video_index
        stop_browse_reason = ""
        ran_out_of_list = False

        if _is_keyword_mode(config) and start_video_index > 0:
            ctx.phase_log.append(
                f"STEP3c resume_from_index={start_video_index} "
                f"aweme_ids={len(aweme_ids)} posters={await _count_search_posters(page)}"
            )
            if not await _ensure_search_item_index(ctx, start_video_index):
                ctx.phase_log.append(
                    f"LIST_SCROLL miss index={start_video_index} "
                    f"posters={await _count_search_posters(page)}"
                )
                await _report_step(
                    ctx,
                    f"续扫：列表滚动到第 {start_video_index + 1} 个视频失败",
                    sub="将尝试直接点击该序号",
                    log=False,
                    progress_force=True,
                )
            else:
                aweme_ids = list(ctx.state.get("search_aweme_ids") or [])
                await _report_step(
                    ctx,
                    f"续扫：从第 {start_video_index + 1} 个视频继续",
                    sub=f"列表已就绪 · 已浏览 {start_video_index} 个",
                    log=False,
                    progress_force=True,
                    progress_extra={"start_video_index": start_video_index},
                )

        while len(all_leads) < target and video_index < batch_end:
            ctx.phase_log.append(
                f"STEP4 video_index={video_index} "
                f"aweme_ids={len(aweme_ids)} posters={await _count_search_posters(page)}"
            )
            await _report_step(
                ctx,
                f"步骤 4/7：浏览视频 {video_index + 1}",
                sub=f"精准线索 {len(all_leads)}/{target} · 继续直到凑够",
                log=False,
                progress_force=True,
                progress_extra={
                    "video_index": video_index,
                    "videos_processed": result.videos_processed,
                    "leads_qualified": len(all_leads),
                    "comments_scanned": result.comments_scanned,
                    "target_leads": target,
                },
            )
            if _is_manual_mode(config):
                if video_index < len(manual_video_urls):
                    video_url = manual_video_urls[video_index]
                else:
                    break
            elif video_index < len(ctx.video_urls):
                video_url = ctx.video_urls[video_index]
            elif video_index < len(aweme_ids) and aweme_ids[video_index]:
                video_url = f"https://www.douyin.com/video/{aweme_ids[video_index]}"
            else:
                video_url = ""
                if _is_keyword_mode(config):
                    if not await _ensure_search_item_index(ctx, video_index):
                        ctx.phase_log.append(
                            f"LIST_EXHAUSTED index={video_index} "
                            f"aweme={len(list(ctx.state.get('search_aweme_ids') or []))} "
                            f"posters={await _count_search_posters(page)}"
                        )
                        ran_out_of_list = True
                        break
                else:
                    ran_out_of_list = True
                    break

            try:
                video_leads, scanned, stop_note = await _browse_video_comments(
                    ctx,
                    config=config,
                    video_index=video_index,
                    video_url=video_url,
                    seen_comment_ids=seen_comment_ids,
                    outreach_stats=outreach_stats,
                    dedupe_stats=dedupe_stats,
                    db_session=db_session,
                    leads_before=len(all_leads),
                )
            except HumanBrowseGuardError as exc:
                ctx.phase_log.append(f"GUARD_VIDEO index={video_index + 1} {str(exc)[:120]}")
                video_leads, scanned, stop_note = [], 0, f"本视频浏览中断：{exc}"
                with contextlib.suppress(Exception):
                    await _close_video_browse(ctx)
            except Exception as exc:
                ctx.phase_log.append(f"VIDEO_SKIP index={video_index + 1} {str(exc)[:120]}")
                _logger.warning("browse video failed index=%s: %s", video_index + 1, exc)
                video_leads, scanned, stop_note = [], 0, f"本视频异常：{exc}"
                with contextlib.suppress(Exception):
                    await _close_video_browse(ctx)
            all_leads.extend(video_leads)
            result.comments_scanned += scanned
            result.videos_processed += 1
            ctx.phase_log.append(
                f"STEP7 video={video_index + 1} leads={len(video_leads)} "
                f"total={len(all_leads)}/{target} scanned={scanned} note={stop_note}"
            )
            await _report_step(
                ctx,
                f"视频 {video_index + 1} 评论扫描完成",
                sub=(
                    f"本视频 +{len(video_leads)} 精准 · 累计 {len(all_leads)}/{target} · "
                    f"扫描 {scanned} 条评论"
                ),
                log=False,
                progress_force=True,
                progress_extra={
                    "video_index": video_index,
                    "videos_processed": result.videos_processed,
                    "leads_qualified": len(all_leads),
                    "comments_scanned": result.comments_scanned,
                    "target_leads": target,
                },
            )
            await human_delay(page, settings, tenant_id=tenant_id, profile="fast")

            if len(all_leads) >= target:
                stop_browse_reason = f"已达目标 {target} 条精准线索"
                break
            if stop_note.startswith("已达目标精准线索"):
                break

            video_index += 1

        result.target_reached = len(all_leads) >= target
        _flush_unpersisted_leads(
            db_session=db_session,
            settings=settings,
            tenant_id=tenant_id,
            config=config,
            leads=all_leads,
            phase_log=ctx.phase_log,
        )
        result.precise_leads = all_leads
        result.comments_persisted = sum(1 for lead in all_leads if lead.persisted)
        result.duplicates_skipped = int(dedupe_stats.get("duplicates_skipped") or 0)
        result.ok = result.target_reached or bool(all_leads) or result.videos_processed > 0
        result.search_exhausted = (
            not result.target_reached
            and (
                ran_out_of_list
                or (
                    _is_manual_mode(config)
                    and video_index >= len(manual_video_urls)
                    and len(all_leads) < target
                )
            )
        )
        result.phase_log = list(ctx.phase_log)
        if result.target_reached:
            result.diagnostic = (
                f"已找到 {len(all_leads)} 条精准线索（目标 {target}），"
                f"浏览 {result.videos_processed} 个视频，去重跳过 {result.duplicates_skipped} 条"
            )
            if stop_browse_reason:
                result.diagnostic += f"；{stop_browse_reason}"
        else:
            if result.search_exhausted:
                result.error = result.error or "E_TARGET_NOT_MET"
            result.diagnostic = (
                f"未凑够目标：精准线索 {len(all_leads)}/{target}，"
                f"已浏览 {result.videos_processed} 个视频"
            )
            if not result.search_exhausted:
                result.diagnostic += "；搜索结果内仍有视频，将继续浏览直至达成目标或列表耗尽"
            elif ran_out_of_list:
                result.diagnostic += "；搜索列表已耗尽"
        await _report_step(
            ctx,
            "步骤 7/7：完成" if result.target_reached else "未达目标",
            sub=result.diagnostic or "",
            log=False,
        )

        payload = {
            "platform": PLATFORM,
            "keyword": config.keyword or subject,
            "acquisition_mode": config.acquisition_mode,
            "source_url": result.source_url,
            "video_url": config.video_url or None,
            "profile_url": config.profile_url or None,
            "search_url": result.search_url,
            "capture_method": capture_method_for_mode(config.acquisition_mode),
            "videos_processed": result.videos_processed,
            "comments_scanned": result.comments_scanned,
            "duplicates_skipped": result.duplicates_skipped,
            "unique_comments_seen": len(seen_comment_ids),
            "precise_lead_count": len(all_leads),
            "precise_leads": _serialize_leads(all_leads),
            "phase_log": result.phase_log,
            "outreach_stats": outreach_stats,
            "target_precise_leads": target,
            "target_reached": result.target_reached,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        output = (
            settings.report_output_dir
            / f"standalone_douyin_{tenant_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        result.output_file = str(output)

    except HumanBrowseGuardError as exc:
        _apply_partial_salvage(
            result,
            all_leads,
            exc=exc,
            ctx=ctx,
            config=config,
            db_session=db_session,
            dedupe_stats=dedupe_stats,
            target=target,
            error_code="E_GUARD",
        )
        await _report_step(
            ctx,
            "会话门禁中断" if not all_leads else f"会话中断 · 已保留 {len(all_leads)} 条线索",
            sub=(result.diagnostic or str(exc))[:120],
            log=False,
        )
    except Exception as exc:
        _apply_partial_salvage(
            result,
            all_leads,
            exc=exc,
            ctx=ctx,
            config=config,
            db_session=db_session,
            dedupe_stats=dedupe_stats,
            target=target,
            error_code="E_RUNTIME",
        )
        await _report_step(ctx, "运行出错（已尽量保留线索）", sub=str(exc)[:120], log=False)
        _logger.exception("standalone browse aborted: %s", exc)

    return result


def build_standalone_browse_config(
    *,
    acquisition_mode: str = "keyword_auto",
    keyword: str = "",
    video_url: str = "",
    profile_url: str = "",
    input_url: str = "",
    days: int = 7,
    video_publish_days: int | None = None,
    comment_days: int | None = None,
    target_precise_leads: int = 3,
    limit: int | None = None,
    max_videos_to_browse: int | None = None,
    max_comments_per_video: int | None = None,
    comment_scroll_rounds: int | None = None,
    match_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    execute_outreach: bool = False,
    test_all_outreach: bool = False,
    reply_text: str = "",
    dm_text: str = "",
    comment_ratio: int = 50,
    dm_ratio: int = 30,
    follow_ratio: int = 20,
    persist_to_db: bool = False,
    start_video_index: int | None = None,
    resume_search_url: str = "",
    source_job_id: str = "",
    close_browser_after: bool = False,
) -> StandaloneKeywordBrowseConfig:
    mode, resolved_video, resolved_profile = resolve_standalone_acquisition_mode(
        acquisition_mode=acquisition_mode,
        input_url=input_url,
        video_url=video_url,
        profile_url=profile_url,
    )
    target = max(1, int(target_precise_leads or limit or 3))
    if mode == "account_home":
        max_videos = max(1, int(max_videos_to_browse or 10))
        search_content_limit = max_videos
    else:
        max_videos = max(1, int(max_videos_to_browse or 50))
        search_content_limit = max(10, min(30, max_videos))
    comments_cap = max(
        120,
        int(max_comments_per_video or 0) or max(300, target * 40),
    )
    scroll_rounds = max(
        24,
        int(comment_scroll_rounds or 0) or max(60, comments_cap // 5),
    )
    return StandaloneKeywordBrowseConfig(
        keyword=str(keyword or "").strip(),
        acquisition_mode=mode,  # type: ignore[arg-type]
        video_url=resolved_video,
        profile_url=resolved_profile,
        input_url=str(input_url or resolved_video or resolved_profile or "").strip(),
        days=int(days),
        video_publish_days=video_publish_days,
        comment_days=comment_days,
        content_limit=search_content_limit,
        target_precise_leads=target,
        max_videos_to_browse=max_videos,
        max_comments_per_video=comments_cap,
        comment_scroll_rounds=scroll_rounds,
        match_keywords=list(match_keywords or []),
        exclude_keywords=list(exclude_keywords or []),
        execute_outreach=bool(execute_outreach),
        test_all_outreach=bool(test_all_outreach),
        reply_text=str(reply_text or "").strip(),
        dm_text=str(dm_text or "").strip(),
        action_policy={
            "comment_ratio": int(comment_ratio),
            "dm_ratio": int(dm_ratio),
            "follow_ratio": int(follow_ratio),
            "interval_min_sec": 10,
            "interval_max_sec": 30,
        },
        persist_to_db=bool(persist_to_db),
        reuse_stable_session=True,
        close_browser_after=bool(close_browser_after),
        start_video_index=max(0, int(start_video_index or 0)),
        resume_search_url=str(resume_search_url or "").strip(),
        source_job_id=str(source_job_id or "").strip(),
    )


def standalone_result_to_response_data(result: StandaloneKeywordBrowseResult) -> dict[str, Any]:
    return {
        "acquisition_mode": result.acquisition_mode,
        "keyword": result.keyword,
        "source_url": result.source_url,
        "search_url": result.search_url,
        "videos_processed": result.videos_processed,
        "comments_scanned": result.comments_scanned,
        "duplicates_skipped": result.duplicates_skipped,
        "precise_lead_count": len(result.precise_leads),
        "target_reached": result.target_reached,
        "phase_log": result.phase_log[-20:],
        "error": result.error,
    }


async def run_standalone_keyword_browse_with_browser(
    settings: Settings,
    *,
    tenant_id: str = "default",
    account_id: str = "default",
    config: StandaloneKeywordBrowseConfig,
    db_session: Session | None = None,
    headless: bool = False,
    on_progress: ProgressCallback | None = None,
) -> StandaloneKeywordBrowseResult:
    """自带浏览器会话的便捷入口（调试 / 脚本调用）。

    默认复用 AgentSessionManager 稳定基座（与桌面 App / Supervisor 相同），
    优先使用已打开的 Chrome 标签，避免每次新建空上下文再灌 Cookie。
    """
    from app.core.antibot import headless_for_platform
    from app.services.agent_browser_session import AgentSessionManager
    from app.services.playwright_pool import PlaywrightPool

    store = DouyinSessionStore(settings)
    resolved_headless = headless_for_platform(settings, PLATFORM, headless)

    if config.reuse_stable_session:
        session = await AgentSessionManager.get_instance().create_stable(
            tenant_id,
            PLATFORM,
            settings,
            account_id=account_id,
            headless=resolved_headless,
        )
        page = session.page
        try:
            result = await run_standalone_keyword_browse(
                page,
                settings,
                tenant_id=tenant_id,
                account_id=account_id,
                config=config,
                db_session=db_session,
                headless=resolved_headless,
                stable_session=session,
                on_progress=on_progress,
            )
        finally:
            await _persist_session_storage(
                store,
                tenant_id=tenant_id,
                account_id=account_id,
                context=session._context,
            )
            if config.close_browser_after:
                await AgentSessionManager.get_instance().close(session.session_id)
        return result

    pool = PlaywrightPool.get()
    async with pool.tenant_context(
        PLATFORM,
        tenant_id,
        store,
        settings,
        headless=resolved_headless,
        account_id=account_id,
    ) as (_context, page):
        return await run_standalone_keyword_browse(
            page,
            settings,
            tenant_id=tenant_id,
            account_id=account_id,
            config=config,
            db_session=db_session,
            headless=resolved_headless,
            on_progress=on_progress,
        )
