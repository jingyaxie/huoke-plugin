from __future__ import annotations

import random
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.core.antibot import human_click, human_delay
from app.services.ui_flow.platforms.douyin.experience import DouyinUiFlowExperience
from app.services.ui_flow.platforms.douyin.feed_ui import (
    activate_comment_sidebar_on_page,
    is_feed_detail_open,
    pause_feed_video_on_page,
)
from app.services.ui_flow.platforms.douyin.search_ui import (
    CAPTURE_METHOD_PREFIX,
    _POSTER_SELECTORS,
    _VIDEO_LINK_SELECTORS,
    collect_video_urls_from_page,
    page_has_search_posters,
)
from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession, UiStepResult

_VIDEO_CARD_SELECTORS = (
    '[data-e2e="search-card-video"]',
    '[class*="SearchVideoCard"]',
    'div.search-result-card',
    '[class*="discover-video-card"]',
    'img.discover-video-card-img',
)


def _exp(ctx: DouyinUiSession) -> DouyinUiFlowExperience | None:
    return ctx.experience if isinstance(ctx.experience, DouyinUiFlowExperience) else None


async def _back_to_search_list(ctx: DouyinUiSession) -> None:
    if ctx.state.get("feed_mode"):
        try:
            await ctx.page.keyboard.press("Escape")
            await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="action")
        except Exception:
            pass
        ctx.state["feed_mode"] = False
    if not await page_has_search_posters(ctx.page):
        search_url = ctx.state.get("search_url") or ""
        if search_url:
            await ctx.page.goto(search_url, wait_until="domcontentloaded", timeout=30000)


async def _resolve_aweme_id_at_index(ctx: DouyinUiSession, index: int) -> str:
    stored = ctx.state.get("search_aweme_ids")
    if isinstance(stored, list) and len(stored) > index:
        return str(stored[index] or "")
    if index < len(ctx.video_urls):
        return ctx.video_urls[index].rstrip("/").split("/")[-1]
    urls = await collect_video_urls_from_page(ctx.page, limit=index + 1)
    if len(urls) > index:
        return urls[index].rstrip("/").split("/")[-1]
    return ""


async def _open_feed_via_modal_id(ctx: DouyinUiSession, aweme_id: str) -> bool:
    if not aweme_id:
        return False
    search_url = str(ctx.state.get("search_url") or ctx.page.url or "")
    if "/search/" not in search_url:
        return False
    parsed = urlparse(search_url)
    query = dict(parse_qsl(parsed.query))
    query["type"] = query.get("type") or "general"
    query["modal_id"] = aweme_id
    modal_url = urlunparse(parsed._replace(query=urlencode(query)))
    try:
        await ctx.page.goto(modal_url, wait_until="domcontentloaded", timeout=45000)
        await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
        from app.services.ui_flow.platforms.douyin.feed_ui import wait_feed_detail

        if await wait_feed_detail(ctx.page, max_sec=6.0):
            ctx.state["feed_mode"] = True
            return True
        clicked = await ctx.page.evaluate(
            """(aweme) => {
              const el = document.querySelector(`[data-aweme-id="${aweme}"]`)
                || [...document.querySelectorAll('[data-aweme-id]')].find(
                  (n) => String(n.getAttribute('data-aweme-id') || '').startsWith(String(aweme).slice(0, 12))
                );
              if (!el) return false;
              el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
              if (typeof el.click === 'function') el.click();
              return true;
            }""",
            aweme_id,
        )
        if clicked:
            await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
            if await wait_feed_detail(ctx.page, max_sec=5.0):
                ctx.state["feed_mode"] = True
                return True
    except Exception:
        return False
    return False


async def _click_video_link_at_index(ctx: DouyinUiSession, index: int) -> bool:
    for selector in _VIDEO_LINK_SELECTORS:
        links = ctx.page.locator(selector)
        count = await links.count()
        if count <= index:
            continue
        link = links.nth(index)
        try:
            await link.scroll_into_view_if_needed(timeout=4000)
            await human_click(ctx.page, link, ctx.settings, tenant_id=ctx.tenant_id)
            await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
            ctx.state["feed_mode"] = True
            return True
        except Exception:
            continue
    return False


async def click_search_poster(ctx: DouyinUiSession, index: int) -> bool:
    """点击搜索列表条目 → Feed 流（modal_id / 海报 / 视频卡片）。"""
    await _back_to_search_list(ctx)

    aweme_id = await _resolve_aweme_id_at_index(ctx, index)
    if aweme_id and await _open_feed_via_modal_id(ctx, aweme_id):
        return True

    exp = _exp(ctx)
    selectors = (*_POSTER_SELECTORS, *_VIDEO_CARD_SELECTORS)
    if exp:
        selectors = exp.prefer("BROWSE", "poster_selector", selectors)

    for selector in selectors:
        posters = ctx.page.locator(selector)
        count = await posters.count()
        if count <= index:
            continue
        poster = posters.nth(index)
        try:
            await poster.scroll_into_view_if_needed(timeout=4000)
            await human_click(ctx.page, poster, ctx.settings, tenant_id=ctx.tenant_id)
            await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
            ctx.state["feed_mode"] = True
            if exp:
                exp.record_phase("BROWSE", elapsed_ms=0, hints={"poster_selector": selector})
            if await is_feed_detail_open(ctx.page) or ctx.state.get("feed_mode"):
                return True
        except Exception:
            continue

    if await _click_video_link_at_index(ctx, index):
        return True

    if aweme_id and await _open_feed_via_modal_id(ctx, aweme_id):
        from app.services.ui_flow.platforms.douyin.feed_ui import wait_feed_detail

        return await wait_feed_detail(ctx.page, max_sec=4.0)

    return False


async def run_browse(ctx: DouyinUiSession) -> UiStepResult | None:
    if not ctx.state.get("search_ready"):
        return None
    if ctx.browse_index >= ctx.params.content_limit:
        return None

    index = ctx.browse_index
    fallback_url = ctx.video_urls[index] if ctx.browse_index < len(ctx.video_urls) else ""

    ctx.phase_log.append(f"BROWSE click poster index={index}")
    clicked = await click_search_poster(ctx, index)
    if not clicked:
        ctx.browse_index += 1
        return UiStepResult(ok=False, diagnostic=f"未点到第 {index + 1} 个搜索海报")

    feed_open = await is_feed_detail_open(ctx.page)
    ctx.phase_log.append(f"BROWSE feed_open={feed_open}")

    lo = max(3, ctx.params.watch_seconds_min)
    hi = max(lo, ctx.params.watch_seconds_max)
    watch_sec = random.randint(lo, hi)
    await ctx.page.wait_for_timeout(watch_sec * 1000)

    sidebar_ok = False
    if ctx.params.inline_ui_outreach:
        await pause_feed_video_on_page(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
        sidebar_ok = await activate_comment_sidebar_on_page(
            ctx.page,
            ctx.settings,
            tenant_id=ctx.tenant_id,
        )
        ctx.phase_log.append(f"BROWSE sidebar={'ok' if sidebar_ok else 'miss'} inline=1")

    ctx.browse_index += 1
    ctx.state["last_browse_url"] = fallback_url or ctx.page.url
    return UiStepResult(
        ok=True,
        data={
            "feed_mode": True,
            "feed_open": feed_open,
            "sidebar_ok": sidebar_ok,
            "capture_method": f"{CAPTURE_METHOD_PREFIX}search_poster_feed",
        },
    )
