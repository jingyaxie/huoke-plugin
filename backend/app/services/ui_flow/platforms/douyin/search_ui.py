from __future__ import annotations

import asyncio
import contextlib
import random
import re
from urllib.parse import quote

from app.core.antibot import human_click, human_delay, human_type
from app.services.ui_flow.platforms.douyin.experience import DouyinUiFlowExperience
from app.services.ui_flow.platforms.douyin.search_parse import (
    analyze_search_api_response,
    extract_aweme_items_from_json,
    is_search_result_api,
    mark_search_api_flags,
    rank_search_items,
    search_api_min_items,
    search_nil_type,
)
from app.services.ui_flow.platforms.douyin.ui_session import DouyinUiSession, UiStepResult

CAPTURE_METHOD_PREFIX = "ui_flow_douyin_"

_SEARCH_INPUT = '[data-e2e="searchbar-input"]'
_SEARCH_INPUT_FALLBACKS = (
    '[data-e2e="searchbar-input"]',
    'input[data-e2e="searchbar-input"]',
    'input[placeholder*="搜索"]',
    '[class*="search"] input[type="text"]',
    'header input[type="text"]',
)
# 搜索列表海报/封面（BROWSE 点它进 Feed；SEARCH 阶段不依赖海报）
_POSTER_SELECTORS = (
    'div.search-result-card',
    '[class*="search-result-card"]',
    '[class*="discover-video-card"]',
    'img.discover-video-card-img',
    '[data-e2e="search-card-video"] img',
    '[data-e2e="search-card-video"]',
    '[class*="SearchVideoCard"] img',
    '[class*="videoImage"] img',
)
_VIDEO_LINK_SELECTORS = (
    'a[href*="/video/"]',
    '[data-e2e="search-card-video"] a',
)
_SEARCH_WHEEL_TARGETS = (
    '[data-e2e="search-card-video"]',
    'div.search-result-card',
    '[class*="SearchVideoCard"]',
    '[class*="search-result-card"]',
)
_SEARCH_RESULTS_SCROLL_JS = """
(delta) => {
  const active = document.activeElement;
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
    active.blur();
  }
  const pickScrollParent = (anchor) => {
    let node = anchor;
    for (let i = 0; i < 14 && node; i++) {
      const sh = node.scrollHeight || 0;
      const ch = node.clientHeight || 0;
      if (sh > ch + 40) return node;
      node = node.parentElement;
    }
    return null;
  };
  const selectors = [
    '[data-e2e="search-card-video"]',
    'div.search-result-card',
    '[class*="SearchVideoCard"]',
    '[class*="search-result"]',
  ];
  let target = null;
  for (const sel of selectors) {
    const anchor = document.querySelector(sel);
    if (!anchor) continue;
    target = pickScrollParent(anchor);
    if (target) break;
  }
  if (!target) {
    target = document.scrollingElement || document.documentElement;
  }
  const before = target.scrollTop || 0;
  const step = Math.max(24, Math.min(120, Number(delta) || 72));
  const maxTop = Math.max(0, (target.scrollHeight || 0) - (target.clientHeight || 0));
  target.scrollTop = Math.min(before + step, maxTop);
  return target.scrollTop > before;
}
"""


def _human_scroll_total(delta_y: int | None) -> int:
    if delta_y is not None:
        return max(180, min(int(delta_y), 520))
    return random.randint(260, 420)


async def _search_results_wheel_point(page) -> tuple[float, float] | None:
    """wheel 落点：列表左缘空白，避免落在封面/标题可点击区。"""
    for selector in _SEARCH_WHEEL_TARGETS:
        loc = page.locator(selector).first
        try:
            if not await loc.count() or not await loc.is_visible():
                continue
            box = await loc.bounding_box()
            if not box or box["y"] < 72:
                continue
            x = max(12.0, box["x"] - 16.0)
            y = box["y"] + box["height"] * 0.55
            return x, y
        except Exception:
            continue
    return None


async def _search_results_safe_focus_point(page) -> tuple[float, float]:
    """释放焦点用的安全坐标（不点在视频卡片上）。"""
    for selector in (
        '[class*="search-tab"]',
        '[class*="SearchTab"]',
        '[class*="tab"]',
        "main",
    ):
        loc = page.locator(selector).first
        try:
            if not await loc.count() or not await loc.is_visible():
                continue
            box = await loc.bounding_box()
            if not box or box["height"] < 20:
                continue
            x = box["x"] + min(48, box["width"] * 0.12)
            y = box["y"] + min(28, box["height"] * 0.5)
            if y > 64:
                return x, y
        except Exception:
            continue
    point = await _search_results_wheel_point(page)
    if point is not None:
        return point
    return 48.0, 420.0


async def _close_search_video_modal_if_open(page) -> None:
    """搜索列表页误点封面会带上 modal_id；回到列表再滚。"""
    url = page.url or ""
    if "/search/" not in url.lower() or "modal_id=" not in url.lower():
        return
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.35)
    url = page.url or ""
    if "modal_id=" not in url.lower():
        return
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() != "modal_id"]
    clean = urlunparse(parsed._replace(query=urlencode(query)))
    if clean != url:
        with contextlib.suppress(Exception):
            await page.goto(clean, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(0.4)


async def _human_wheel_segments(
    page,
    settings,
    *,
    tenant_id: str,
    total: int,
    point: tuple[float, float] | None = None,
) -> None:
    """分段 wheel + 随机停顿，模拟真人浏览搜索结果。"""
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
    steps = random.randint(5, 9)
    per_step = max(28, total // steps)
    scrolled_any = False
    for _ in range(steps):
        step = per_step + random.randint(-10, 10)
        with contextlib.suppress(Exception):
            if await page.evaluate(_SEARCH_RESULTS_SCROLL_JS, step):
                scrolled_any = True
        await asyncio.sleep(random.uniform(0.14, 0.38))
    return scrolled_any


async def release_searchbar_focus(page) -> None:
    """搜索提交后焦点常在顶栏输入框；只 blur/移鼠标，不点击视频卡片（会打开 modal）。"""
    with contextlib.suppress(Exception):
        await page.evaluate(
            """() => {
              const active = document.activeElement;
              if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
                active.blur();
              }
              if (document.body && document.body.focus) {
                document.body.focus({ preventScroll: true });
              }
            }"""
        )
    with contextlib.suppress(Exception):
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.12)
    await _close_search_video_modal_if_open(page)
    x, y = await _search_results_safe_focus_point(page)
    with contextlib.suppress(Exception):
        await page.mouse.move(x, y)


async def scroll_search_results_page(
    page,
    settings,
    *,
    tenant_id: str = "default",
    delta_y: int | None = None,
) -> bool:
    """在搜索结果列表区域滚动（先释放搜索框焦点，再分段慢速滚）。"""
    await _close_search_video_modal_if_open(page)
    total = _human_scroll_total(delta_y)
    await release_searchbar_focus(page)
    await asyncio.sleep(random.uniform(0.25, 0.65))

    point = await _search_results_wheel_point(page)
    if point is not None:
        await _human_wheel_segments(page, settings, tenant_id=tenant_id, total=total, point=point)
        return True

    if await _human_dom_scroll_steps(page, total):
        await human_delay(page, settings, tenant_id=tenant_id, profile="scroll")
        return True

    await _human_wheel_segments(page, settings, tenant_id=tenant_id, total=total, point=None)
    return False


async def _scroll_results(ctx: DouyinUiSession, *, delta_y: int | None = None) -> bool:
    return await scroll_search_results_page(
        ctx.page,
        ctx.settings,
        tenant_id=ctx.tenant_id,
        delta_y=delta_y,
    )


async def collect_video_urls_from_page(page, *, limit: int) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for selector in _VIDEO_LINK_SELECTORS:
        try:
            links = await page.locator(selector).evaluate_all(
                "els => els.map(e => e.href || e.getAttribute('href') || '')"
            )
        except Exception:
            continue
        for href in links or []:
            clean = _normalize_video_href(str(href))
            if clean and clean not in seen:
                seen.add(clean)
                urls.append(clean)
            if len(urls) >= limit:
                return urls[:limit]
    return urls[:limit]


def _normalize_video_href(href: str) -> str | None:
    text = (href or "").strip()
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    if text.startswith("/"):
        text = f"https://www.douyin.com{text}"
    match = re.search(r"(https?://[^\"']+/video/\d{8,22})", text)
    if match:
        return match.group(1).split("?")[0]
    match = re.search(r"/video/(\d{8,22})", text)
    if match:
        return f"https://www.douyin.com/video/{match.group(1)}"
    return None


def _on_search_results_page(url: str) -> bool:
    u = (url or "").lower()
    return "/search/" in u


_JINGXUAN_HOME = "https://www.douyin.com/jingxuan"


def _jingxuan_search_url(keyword: str) -> str:
    return f"https://www.douyin.com/jingxuan/search/{quote(keyword.strip())}?type=general"


def _www_search_url(keyword: str) -> str:
    return f"https://www.douyin.com/search/{quote(keyword.strip())}?type=general"


def _is_general_search_page(url: str) -> bool:
    u = (url or "").lower()
    return _on_search_results_page(u) and "type=video" not in u


async def _search_page_has_results(page) -> bool:
    return bool(await page_has_search_posters(page) or await page_has_video_results(page))


async def _submit_searchbar_keyword(ctx: DouyinUiSession, keyword: str) -> None:
    search_input = await _search_input_locator(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
    if await search_input.count() == 0:
        return
    await _human_type_one_per_second(ctx, search_input, keyword)
    await _submit_search(ctx, keyword=keyword)


async def _search_input_locator(page, settings=None, tenant_id: str = "default"):
    with contextlib.suppress(Exception):
        placeholder = page.get_by_placeholder("搜索你感兴趣的内容").first
        if await placeholder.count() > 0 and await placeholder.is_visible():
            return placeholder
    with contextlib.suppress(Exception):
        placeholder = page.locator('input[placeholder*="搜索"]').first
        if await placeholder.count() > 0 and await placeholder.is_visible():
            return placeholder

    selectors = list(_SEARCH_INPUT_FALLBACKS)
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if await loc.count() > 0 and await loc.is_visible():
                return loc
        except Exception:
            continue
    return page.locator(_SEARCH_INPUT).first


def _on_search_results_url(url: str) -> bool:
    """必须在搜索页 URL 上才算搜索完成（精选首页有视频卡片，不能误判）。"""
    return _on_search_results_page(url) or "/jingxuan/search/" in (url or "").lower()


async def _wait_search_page_results(
    ctx: DouyinUiSession,
    *,
    rounds: int = 6,
    allow_scroll: bool | None = None,
) -> bool:
    if allow_scroll is None:
        allow_scroll = not ctx.params.inline_ui_outreach
    for i in range(rounds):
        if _on_search_results_url(ctx.page.url) and await _search_page_has_results(ctx.page):
            return True
        if i < 2:
            await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
            continue
        await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
        if allow_scroll:
            await _scroll_results(ctx)
    return _on_search_results_url(ctx.page.url) and await _search_page_has_results(ctx.page)


async def _ensure_searchbar_ready(ctx: DouyinUiSession) -> bool:
    """确保在精选首页且搜索框可见（仅 goto 首页，不拼接搜索 URL）。"""
    loc = await _search_input_locator(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
    try:
        if await loc.count() > 0 and await loc.is_visible():
            return True
    except Exception:
        pass

    if "/jingxuan" not in (ctx.page.url or ""):
        try:
            await ctx.page.goto(_JINGXUAN_HOME, wait_until="domcontentloaded", timeout=45000)
            await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="page_load")
        except Exception:
            pass

    for _ in range(10):
        try:
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            pass
        await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
    return False


async def _focus_search_input_via_dom(page) -> bool:
    """用 DOM 聚焦可见的顶栏搜索框（系统 Chrome 下比 locator.click 更可靠）。"""
    try:
        return bool(
            await page.evaluate(
                """() => {
                    const inputs = Array.from(document.querySelectorAll('input'));
                    const el = inputs.find((node) => {
                        const ph = node.getAttribute('placeholder') || '';
                        if (!ph.includes('搜索')) return false;
                        const rect = node.getBoundingClientRect();
                        return rect.width > 80 && rect.height > 10 && rect.top >= 0;
                    });
                    if (!el) return false;
                    el.scrollIntoView({ block: 'center', inline: 'center' });
                    el.focus();
                    el.click();
                    return true;
                }"""
            )
        )
    except Exception:
        return False


async def _type_into_focused_search_input(page, text: str) -> bool:
    """搜索框已聚焦后逐字写入（不再重复 focus/click）。"""
    try:
        return bool(
            await page.evaluate(
                """async (text) => {
                    let el = document.activeElement;
                    if (!el || el.tagName !== 'INPUT') {
                        el = Array.from(document.querySelectorAll('input')).find((node) => {
                            const ph = node.getAttribute('placeholder') || '';
                            const rect = node.getBoundingClientRect();
                            return ph.includes('搜索') && rect.width > 80 && rect.height > 10 && rect.top >= 0;
                        });
                    }
                    if (!el) return false;
                    if (document.activeElement !== el) {
                        el.focus();
                    }
                    const target = String(text || '');
                    el.value = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    for (const ch of target) {
                        el.value += ch;
                        el.dispatchEvent(new InputEvent('input', { bubbles: true, data: ch, inputType: 'insertText' }));
                        await new Promise((r) => setTimeout(r, 850 + Math.floor(Math.random() * 250)));
                    }
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return (el.value || '').trim() === target.trim();
                }""",
                text,
            )
        )
    except Exception:
        return False


async def _activate_searchbar(ctx: DouyinUiSession, search_input) -> None:
    """先可见点击搜索栏，再输入（避免未聚焦就打字）。"""
    page = ctx.page
    await search_input.scroll_into_view_if_needed()
    await human_click(page, search_input, ctx.settings, tenant_id=ctx.tenant_id)
    await asyncio.sleep(random.uniform(0.45, 0.95))
    with contextlib.suppress(Exception):
        await search_input.focus()


async def _clear_search_input(ctx: DouyinUiSession, search_input) -> None:
    current = await _read_search_input_value(ctx)
    if not current:
        return
    with contextlib.suppress(Exception):
        await search_input.fill("")
    with contextlib.suppress(Exception):
        await ctx.page.evaluate(
            """() => {
              const el = document.activeElement;
              if (el && el.tagName === 'INPUT') {
                el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
              }
            }"""
        )
    await asyncio.sleep(random.uniform(0.15, 0.35))


async def _human_type_one_per_second(
    ctx: DouyinUiSession,
    search_input,
    keyword: str,
) -> None:
    """模拟人类：先点搜索框 → 清空 → 逐字输入一次。"""
    from app.core.antibot import antibot_suppressed_for_page

    text = str(keyword or "").strip()
    if not text:
        return
    page = ctx.page

    await _activate_searchbar(ctx, search_input)

    if await _read_search_input_value(ctx) == text:
        return

    await _clear_search_input(ctx, search_input)

    if antibot_suppressed_for_page(page):
        # 系统 Chrome：Playwright fill 才能同步 React；逐字 press 后校验失败会误触发清空。
        await human_type(page, search_input, text, ctx.settings, tenant_id=ctx.tenant_id, clear_first=False)
        await asyncio.sleep(random.uniform(0.25, 0.45))
        if await _read_search_input_value(ctx) != text:
            with contextlib.suppress(Exception):
                await _focus_search_input_via_dom(page)
            await human_type(page, search_input, text, ctx.settings, tenant_id=ctx.tenant_id, clear_first=True)
    else:
        typed_ok = await _type_into_focused_search_input(page, text)
        if not typed_ok:
            for char in text:
                with contextlib.suppress(Exception):
                    await search_input.press_sequentially(char, delay=30)
                await asyncio.sleep(random.uniform(0.85, 1.1))
        if await _read_search_input_value(ctx) != text:
            await human_type(
                page,
                search_input,
                text,
                ctx.settings,
                tenant_id=ctx.tenant_id,
                clear_first=False,
            )


async def _search_via_searchbar_ui(
    ctx: DouyinUiSession,
    keyword: str,
    *,
    allow_scroll: bool | None = None,
) -> bool:
    """精选页：随机停顿 → 聚焦搜索框 → 逐字输入 → 点搜索。"""
    if not await _ensure_searchbar_ready(ctx):
        return False
    ctx.state.pop("search_submitted", None)

    with contextlib.suppress(Exception):
        await ctx.page.bring_to_front()
    await asyncio.sleep(random.uniform(0.5, 1.5))

    search_input = await _search_input_locator(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
    if await search_input.count() == 0:
        return False

    await _human_type_one_per_second(ctx, search_input, keyword)
    await asyncio.sleep(random.uniform(0.3, 0.6))
    await _submit_search(ctx, keyword=keyword)
    return await _wait_search_page_results(ctx, rounds=12, allow_scroll=allow_scroll)


async def _search_via_searchbar(ctx: DouyinUiSession, keyword: str) -> bool:
    """通过搜索框输入关键词并提交，避免直接 goto 拼接的搜索 URL。"""
    if not await _ensure_searchbar_ready(ctx):
        return False
    ctx.state.pop("search_submitted", None)
    search_input = await _search_input_locator(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
    if await search_input.count() == 0:
        return False
    await _human_type_one_per_second(ctx, search_input, keyword)
    await _submit_search(ctx, keyword=keyword)
    return await _wait_search_page_results(ctx, rounds=8)


async def _navigate_to_search_results(ctx: DouyinUiSession, keyword: str) -> bool:
    """打开综合搜索结果页；优先搜索框输入，直接 URL 仅作最后兜底。"""
    if _is_general_search_page(ctx.page.url) and await _search_page_has_results(ctx.page):
        return True

    if await _search_via_searchbar(ctx, keyword):
        return True

    async def _goto_and_wait(url: str) -> bool:
        try:
            await ctx.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="page_load")
        except Exception:
            return False
        return await _wait_search_page_results(ctx, rounds=5)

    if await _goto_and_wait(_jingxuan_search_url(keyword)):
        return True

    if _is_general_search_page(ctx.page.url):
        await _submit_searchbar_keyword(ctx, keyword)
        if await _wait_search_page_results(ctx):
            return True

    if await _goto_and_wait(_www_search_url(keyword)):
        return True

    return _is_general_search_page(ctx.page.url) and await _search_page_has_results(ctx.page)


async def _await_search_single_api(
    ctx: DouyinUiSession,
    api_items: dict[str, dict],
    *,
    limit: int,
    timeout_s: float = 18.0,
    allow_scroll: bool = True,
    flags: dict[str, bool] | None = None,
) -> None:
    """精选综合搜索：优先依据已拦截的 search/single 判定完成，DOM 仅作补充。"""
    need = search_api_min_items(limit)
    if len(api_items) >= need:
        return
    if flags and flags.get("api_complete") and (len(api_items) >= 1 or flags.get("api_explicit_empty")):
        return
    if len(api_items) >= 1 and await page_has_search_posters(ctx.page):
        return
    if flags and flags.get("api_complete"):
        timeout_s = min(timeout_s, 4.0)
        allow_scroll = False
    elif await page_has_search_posters(ctx.page):
        timeout_s = min(timeout_s, 6.0)

    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline and len(api_items) < need:
        if flags and flags.get("api_complete"):
            return
        remaining_ms = max(
            400,
            int((deadline - asyncio.get_running_loop().time()) * 1000),
        )
        try:
            async with ctx.page.expect_response(
                lambda r: is_search_result_api(r.url) and r.status < 400,
                timeout=min(remaining_ms, 8000),
            ) as resp_info:
                if allow_scroll:
                    await _scroll_results(ctx)
                else:
                    await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
            data = await (await resp_info.value).json()
            outcome = analyze_search_api_response(data, min_items=need)
            if flags is not None:
                mark_search_api_flags(flags, outcome)
            for row in extract_aweme_items_from_json(data):
                api_items.setdefault(row["aweme_id"], row)
            if len(api_items) >= need or (flags and flags.get("api_complete")):
                return
        except Exception:
            await asyncio.sleep(0.35)
            if allow_scroll:
                await _scroll_results(ctx)


async def _finalize_search_success(
    ctx: DouyinUiSession,
    *,
    api_items: dict[str, dict],
    limit: int,
    capture_method: str,
    diagnostic: str,
    allow_scroll: bool = True,
    flags: dict[str, bool] | None = None,
) -> UiStepResult:
    await release_searchbar_focus(ctx.page)
    need = search_api_min_items(limit)
    if len(api_items) >= need or (flags and flags.get("api_complete")):
        await _await_search_single_api(
            ctx,
            api_items,
            limit=limit,
            timeout_s=2.0,
            allow_scroll=False,
            flags=flags,
        )
    elif await page_has_search_posters(ctx.page):
        await _await_search_single_api(
            ctx,
            api_items,
            limit=limit,
            timeout_s=6.0,
            allow_scroll=False,
            flags=flags,
        )
    else:
        await _await_search_single_api(
            ctx,
            api_items,
            limit=limit,
            allow_scroll=allow_scroll,
            flags=flags,
        )
    dom_wait_rounds = 2 if api_items or (flags and flags.get("api_complete")) else 6
    for _ in range(dom_wait_rounds):
        if api_items or await collect_video_urls_from_page(ctx.page, limit=1):
            break
        await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
        if allow_scroll and not ctx.params.inline_ui_outreach:
            await _scroll_results(ctx)

    video_urls = await _collect_results(ctx, api_items=api_items, limit=limit)
    poster_mode = not video_urls and (await page_has_search_posters(ctx.page) or bool(api_items))
    if not video_urls and not poster_mode:
        return UiStepResult(
            ok=False,
            error="E_NO_CONTENT",
            diagnostic=f"搜索页无视频结果；页 {ctx.page.url}",
        )
    ctx.video_urls = video_urls
    ctx.state["search_ready"] = True
    ctx.state["search_url"] = ctx.page.url
    aweme_ids: list[str] = []
    if api_items:
        aweme_ids = [
            str(row.get("aweme_id") or "")
            for row in rank_search_items(list(api_items.values()), ctx.params.keyword)
            if str(row.get("aweme_id") or "")
        ]
        ctx.state["search_aweme_ids"] = aweme_ids
    if poster_mode:
        ctx.state["search_poster_mode"] = True
    return UiStepResult(
        ok=True,
        data={
            "video_urls": video_urls,
            "capture_method": capture_method,
            "search_url": ctx.page.url,
            "poster_mode": poster_mode,
            "search_aweme_ids": aweme_ids,
        },
        diagnostic=diagnostic,
    )


async def page_has_search_posters(page) -> bool:
    for selector in _POSTER_SELECTORS:
        try:
            if await page.locator(selector).count():
                return True
        except Exception:
            continue
    return bool(await collect_video_urls_from_page(page, limit=1))


async def page_has_video_results(page) -> bool:
    return bool(await collect_video_urls_from_page(page, limit=1))


def _exp(ctx: DouyinUiSession) -> DouyinUiFlowExperience | None:
    return ctx.experience if isinstance(ctx.experience, DouyinUiFlowExperience) else None


async def _read_search_input_value_dom(page) -> str:
    """从 DOM 读取搜索框 value（React 受控时比 input_value 更可靠）。"""
    try:
        return str(
            await page.evaluate(
                """() => {
                    const nodes = Array.from(document.querySelectorAll('input'));
                    const el = nodes.find((node) => {
                        const e2e = node.getAttribute('data-e2e') || '';
                        if (e2e === 'searchbar-input') return true;
                        const ph = node.getAttribute('placeholder') || '';
                        const rect = node.getBoundingClientRect();
                        return ph.includes('搜索') && rect.width > 80 && rect.height > 10;
                    });
                    return el && el.value ? String(el.value).trim() : '';
                }"""
            )
            or ""
        ).strip()
    except Exception:
        return ""


async def _read_search_input_value(ctx: DouyinUiSession) -> str:
    try:
        loc = await _search_input_locator(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
        if await loc.count():
            value = (await loc.input_value() or "").strip()
            if value:
                return value
            dom_value = await _read_search_input_value_dom(ctx.page)
            if dom_value:
                return dom_value
            with contextlib.suppress(Exception):
                return (await loc.inner_text() or "").strip()
    except Exception:
        pass
    return await _read_search_input_value_dom(ctx.page)


async def _ensure_search_input_keyword(
    ctx: DouyinUiSession,
    search_input,
    keyword: str,
) -> bool:
    """提交前确保搜索框里有关键词（不清空已有正确内容）。"""
    text = str(keyword or "").strip()
    if not text:
        return False
    current = await _read_search_input_value(ctx)
    if current == text:
        return True
    page = ctx.page
    with contextlib.suppress(Exception):
        await search_input.focus()
    await human_type(
        page,
        search_input,
        text,
        ctx.settings,
        tenant_id=ctx.tenant_id,
        clear_first=bool(current),
    )
    await asyncio.sleep(random.uniform(0.2, 0.35))
    return await _read_search_input_value(ctx) == text


async def _already_on_search_results(ctx: DouyinUiSession, keyword: str) -> bool:
    if not _is_general_search_page(ctx.page.url):
        return False
    if ctx.params.inline_ui_outreach and "type=video" in (ctx.page.url or "").lower():
        return False
    if await _read_search_input_value(ctx) != keyword:
        return False
    return await _search_page_has_results(ctx.page)


async def page_ready_for_search_reuse(ctx: DouyinUiSession) -> bool:
    """当前标签是否已在目标关键词的综合搜索列表（非视频浮层、非验证码页）。"""
    from app.platforms.douyin.human_guards import is_captcha_page
    from app.services.ui_flow.platforms.douyin.feed_ui import feed_overlay_visible

    keyword = str(ctx.params.keyword or "").strip()
    if not keyword:
        return False
    if await is_captcha_page(ctx.page):
        return False
    if await feed_overlay_visible(ctx.page):
        return False
    return await _already_on_search_results(ctx, keyword)


async def reuse_search_results_if_ready(
    ctx: DouyinUiSession,
    *,
    limit: int | None = None,
) -> UiStepResult | None:
    """已在正确搜索页时复用列表，跳过搜索框重提交（降低 verify_check / 验证码风险）。"""
    if not await page_ready_for_search_reuse(ctx):
        return None

    resolved_limit = max(1, int(limit or ctx.params.content_limit or 10))
    flags: dict[str, bool] = {}
    api_items: dict[str, dict] = {}
    ctx.state["search_submitted"] = True
    ctx.state.setdefault("search_url", ctx.page.url)
    if _needs_ui_publish_filter(ctx):
        from app.platforms.search_filters import douyin_publish_time_ui_label, normalize_days

        label = douyin_publish_time_ui_label(normalize_days(ctx.params.days))
        if label:
            ctx.state.setdefault("search_filter_applied", label)

    result = await _finalize_search_success(
        ctx,
        api_items=api_items,
        limit=resolved_limit,
        capture_method=f"{CAPTURE_METHOD_PREFIX}search_ui_reuse",
        diagnostic="复用当前搜索页（跳过搜索框重提交）",
        allow_scroll=False,
        flags=flags,
    )
    return result if result.ok else None


async def _submit_search(ctx: DouyinUiSession, *, keyword: str | None = None) -> None:
    if ctx.state.get("search_submitted"):
        return

    page = ctx.page
    kw = str(keyword or ctx.params.keyword or "").strip()
    search_input = await _search_input_locator(page, ctx.settings, tenant_id=ctx.tenant_id)
    if kw and await search_input.count():
        await _ensure_search_input_keyword(ctx, search_input, kw)

    btn = page.locator('[data-e2e="searchbar-button"]').first

    async def do_submit() -> None:
        if await search_input.count():
            with contextlib.suppress(Exception):
                await search_input.focus()
            await asyncio.sleep(0.12)
        if await btn.count() > 0 and await btn.is_visible():
            await human_click(ctx.page, btn, ctx.settings, tenant_id=ctx.tenant_id)
            return
        text_btn = page.get_by_role("button", name="搜索").first
        if await text_btn.count() > 0 and await text_btn.is_visible():
            await human_click(ctx.page, text_btn, ctx.settings, tenant_id=ctx.tenant_id)
            return
        await page.keyboard.press("Enter")

    navigated = False
    for attempt in range(3):
        if kw and await search_input.count():
            await _ensure_search_input_keyword(ctx, search_input, kw)
        await do_submit()
        for _ in range(12):
            if _on_search_results_url(page.url or ""):
                navigated = True
                break
            await asyncio.sleep(0.35)
        if navigated:
            break
        if attempt < 2:
            with contextlib.suppress(Exception):
                if await search_input.count():
                    await search_input.focus()
                await page.keyboard.press("Enter")

    if navigated:
        await asyncio.sleep(0.5)
        await release_searchbar_focus(page)

    ctx.state["search_submitted"] = navigated
    exp = _exp(ctx)
    if exp:
        exp.record_phase("SEARCH", elapsed_ms=0, hints={"submit": "enter_or_button", "navigated": navigated})


async def _wait_search_results(
    ctx: DouyinUiSession,
    *,
    api_items: dict[str, dict],
    flags: dict[str, bool],
    limit: int,
    keyword: str,
    allow_direct_nav: bool = True,
    allow_scroll: bool | None = None,
) -> bool:
    """等搜索真正完成：优先依据 search/single 接口，DOM 海报/链接仅作补充。"""
    if allow_scroll is None:
        allow_scroll = not ctx.params.inline_ui_outreach
    if flags.get("verify_check"):
        return False

    need = search_api_min_items(limit)

    for _ in range(15):
        if _on_search_results_page(ctx.page.url):
            break
        await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
    else:
        if allow_direct_nav:
            await _navigate_to_search_results(ctx, keyword)
        elif not await _search_via_searchbar(ctx, keyword):
            return False

    if not _on_search_results_page(ctx.page.url):
        return False

    for _ in range(10):
        if flags.get("verify_check"):
            return False
        if flags.get("api_complete"):
            if len(api_items) >= need or flags.get("api_explicit_empty"):
                return True
            if await collect_video_urls_from_page(ctx.page, limit=1) or await page_has_search_posters(ctx.page):
                return True
        if len(api_items) >= need:
            return True
        if len(api_items) >= 1:
            return True
        if await collect_video_urls_from_page(ctx.page, limit=1):
            return True
        if await page_has_search_posters(ctx.page):
            if api_items or flags.get("api_complete"):
                return True
        await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
        if allow_scroll:
            await _scroll_results(ctx)

    return bool(api_items) or bool(await collect_video_urls_from_page(ctx.page, limit=1)) or (
        bool(await page_has_search_posters(ctx.page)) and bool(api_items or flags.get("api_complete"))
    )


async def _wait_post_filter_api(
    ctx: DouyinUiSession,
    api_items: dict[str, dict],
    *,
    flags: dict[str, bool],
    limit: int,
    timeout_s: float = 20.0,
) -> bool:
    """筛选完成后等待新的 search/single 返回，依据接口字段判定完成。"""
    need = search_api_min_items(limit)
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if flags.get("verify_check"):
            return False
        if len(api_items) >= need:
            return True
        if flags.get("api_complete") and (len(api_items) >= 1 or flags.get("api_explicit_empty")):
            return True
        remaining_ms = max(
            300,
            int((deadline - asyncio.get_running_loop().time()) * 1000),
        )
        try:
            async with ctx.page.expect_response(
                lambda r: is_search_result_api(r.url) and r.status < 400,
                timeout=min(remaining_ms, 6000),
            ) as resp_info:
                await human_delay(ctx.page, ctx.settings, tenant_id=ctx.tenant_id, profile="fast")
            data = await (await resp_info.value).json()
            outcome = analyze_search_api_response(data, min_items=need)
            mark_search_api_flags(flags, outcome)
            for row in extract_aweme_items_from_json(data):
                api_items.setdefault(row["aweme_id"], row)
            if len(api_items) >= need or flags.get("api_complete"):
                ctx.state["search_api_complete"] = True
                ctx.state["search_api_complete_reason"] = flags.get("api_complete_reason") or outcome.reason
                return True
        except Exception:
            await asyncio.sleep(0.35)
    return len(api_items) >= need or bool(api_items) or bool(flags.get("api_complete"))


async def _collect_results(ctx: DouyinUiSession, *, api_items: dict[str, dict], limit: int) -> list[str]:
    from app.platforms.search_filters import (
        filter_search_items,
        normalize_days,
        select_rows_after_filter,
    )

    ranked = rank_search_items(list(api_items.values()), ctx.params.keyword)
    days = normalize_days(ctx.params.days)
    if days and not ctx.params.skip_search_filter:
        filtered, _stats = filter_search_items(
            ranked,
            region=ctx.params.region,
            days=days,
            platform=ctx.params.platform or "douyin",
            limit=max(limit * 3, limit),
        )
        ranked = select_rows_after_filter(
            ranked,
            filtered,
            region=ctx.params.region,
            limit=max(limit * 3, limit),
        )
    seen: set[str] = set()
    urls: list[str] = []
    for row in ranked:
        url = (row.get("video_url") or "").split("?")[0]
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= limit:
            return urls[:limit]

    dom_urls = await collect_video_urls_from_page(ctx.page, limit=limit)
    for url in dom_urls:
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls[:limit]


def _searchbar_only(ctx: DouyinUiSession) -> bool:
    """UI 搜索：必须搜索框提交，禁止直接 goto 搜索 URL。"""
    return bool(ctx.params.inline_ui_outreach or ctx.params.ui_search_only)


def _needs_ui_publish_filter(ctx: DouyinUiSession) -> bool:
    from app.platforms.search_filters import douyin_publish_time_ui_label, normalize_days

    if ctx.params.skip_search_filter:
        return False
    return bool(douyin_publish_time_ui_label(normalize_days(ctx.params.days)))


async def _ui_pause(*, min_s: float = 0.8, max_s: float = 1.6) -> None:
    """系统 Chrome 下 antibot delay 会被跳过，筛选 UI 必须显式等待。"""
    await asyncio.sleep(random.uniform(min_s, max_s))


_FILTER_PANEL_MARKERS = ("发布时间", "排序依据", "搜索范围", "内容形式")

_FILTER_BUTTON_POINT_JS = """
() => {
  const nodes = [...document.querySelectorAll('span, div, button, a')];
  const candidates = nodes.filter((n) => {
    const t = (n.textContent || '').trim();
    if (t !== '筛选') return false;
    const r = n.getBoundingClientRect();
    return (
      r.width >= 20 && r.width <= 96 &&
      r.height >= 14 && r.height <= 48 &&
      r.top >= 48 && r.top <= 200 &&
      r.left > 40
    );
  });
  candidates.sort((a, b) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    return ra.width * ra.height - rb.width * rb.height;
  });
  const btn = candidates[0];
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2, top: r.top, height: r.height };
}
"""

_FILTER_PANEL_OPEN_JS = """
() => {
  const markers = ['发布时间', '排序依据', '搜索范围', '内容形式'];
  const blocks = [...document.querySelectorAll('div, section, aside, ul')];
  for (const el of blocks) {
    const r = el.getBoundingClientRect();
    if (r.height < 72 || r.width < 160) continue;
    if (r.top < 72 || r.top > window.innerHeight * 0.72) continue;
    const text = (el.innerText || '').slice(0, 600);
    if (!markers.some((m) => text.includes(m))) continue;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) < 0.05) {
      continue;
    }
    return true;
  }
  return false;
}
"""


async def _is_filter_panel_open(page) -> bool:
    try:
        return bool(await page.evaluate(_FILTER_PANEL_OPEN_JS))
    except Exception:
        return False


async def _wait_filter_panel_open(page, *, timeout_s: float = 14.0) -> bool:
    if await _is_filter_panel_open(page):
        return True
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await _is_filter_panel_open(page):
            return True
        await asyncio.sleep(0.42)
    return False


async def _wait_filter_panel_closed(page, *, timeout_s: float = 10.0) -> bool:
    if not await _is_filter_panel_open(page):
        return True
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if not await _is_filter_panel_open(page):
            return True
        await asyncio.sleep(0.38)
    return not await _is_filter_panel_open(page)


async def _verify_publish_time_filter_applied(page, label: str) -> bool:
    try:
        if await _is_filter_panel_open(page):
            return False
        return bool(
            await page.evaluate(
                """(label) => {
                  const nodes = [...document.querySelectorAll('span, div, button, a')];
                  return nodes.some((n) => {
                    const text = (n.textContent || '').trim();
                    if (text !== label) return false;
                    const rect = n.getBoundingClientRect();
                    return rect.width > 16 && rect.height > 8 && rect.top > 56 && rect.top < window.innerHeight - 24;
                  });
                }""",
                label,
            )
        )
    except Exception:
        return False


async def _filter_button_point(page) -> dict | None:
    try:
        point = await page.evaluate(_FILTER_BUTTON_POINT_JS)
        return point if isinstance(point, dict) else None
    except Exception:
        return None


async def _open_search_filter_panel(ctx: DouyinUiSession) -> str:
    """打开筛选浮层。筛选按钮 hover/聚焦/点击都会触发浮层，避免重复触发导致开关切换。

    返回: already_open | hover | click | failed
    """
    page = ctx.page
    if await _is_filter_panel_open(page):
        return "already_open"

    point = await _filter_button_point(page)
    if not point:
        return "failed"

    vp = page.viewport_size or {"width": 1440, "height": 1200}
    if float(point.get("top") or 0) < 72 or float(point.get("top") or 0) > vp["height"] - 40:
        with contextlib.suppress(Exception):
            await page.evaluate(
                """(y) => {
                  window.scrollBy({ top: y - window.innerHeight * 0.35, behavior: 'instant' });
                }""",
                float(point.get("top") or 200),
            )
        await _ui_pause(min_s=0.6, max_s=1.0)
        point = await _filter_button_point(page)
        if not point:
            return "failed"
        if await _is_filter_panel_open(page):
            return "already_open"

    safe = await _search_results_safe_focus_point(page)
    with contextlib.suppress(Exception):
        await page.mouse.move(safe[0], safe[1])
    await _ui_pause(min_s=0.5, max_s=0.9)

    x = float(point["x"])
    y = float(point["y"])
    with contextlib.suppress(Exception):
        await page.mouse.move(x, y, steps=random.randint(10, 18))
    await _ui_pause(min_s=1.0, max_s=1.7)

    if await _is_filter_panel_open(page):
        return "hover"

    await page.mouse.click(x, y)
    await _ui_pause(min_s=1.2, max_s=2.0)
    if await _is_filter_panel_open(page):
        return "click"
    return "failed"


async def _click_publish_time_option(ctx: DouyinUiSession, label: str) -> bool:
    page = ctx.page
    if not await _is_filter_panel_open(page):
        return False
    await _ui_pause(min_s=0.8, max_s=1.3)
    try:
        point = await page.evaluate(
            """(label) => {
              const markers = ['发布时间', '排序依据', '搜索范围', '内容形式'];
              const blocks = [...document.querySelectorAll('div, section, aside, ul')];
              let panel = null;
              for (const el of blocks) {
                const r = el.getBoundingClientRect();
                if (r.height < 72 || r.width < 160) continue;
                if (r.top < 72 || r.top > window.innerHeight * 0.72) continue;
                const text = (el.innerText || '').slice(0, 600);
                if (!markers.some((m) => text.includes(m))) continue;
                panel = el;
                break;
              }
              const scope = panel || document.body;
              const nodes = [...scope.querySelectorAll('span, div, button, label')];
              const target = nodes.find((n) => (n.textContent || '').trim() === label);
              if (!target) return null;
              const r = target.getBoundingClientRect();
              if (r.width < 8 || r.height < 8) return null;
              return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
            }""",
            label,
        )
        if isinstance(point, dict):
            await page.mouse.click(float(point["x"]), float(point["y"]))
            await _ui_pause(min_s=1.0, max_s=1.6)
            return True
    except Exception:
        pass
    option = page.get_by_text(label, exact=True).first
    try:
        if await option.count() > 0:
            await option.wait_for(state="visible", timeout=5000)
            box = await option.bounding_box()
            if box:
                await page.mouse.click(
                    box["x"] + box["width"] * 0.5,
                    box["y"] + box["height"] * 0.5,
                )
                await _ui_pause(min_s=1.0, max_s=1.6)
                return True
    except Exception:
        pass
    return False


async def _confirm_filter_panel(ctx: DouyinUiSession) -> bool:
    page = ctx.page
    if not await _is_filter_panel_open(page):
        return False
    await _ui_pause(min_s=0.7, max_s=1.2)
    for confirm in ("确定", "完成", "应用"):
        btn = page.get_by_role("button", name=confirm).first
        try:
            if await btn.count() > 0 and await btn.is_visible():
                box = await btn.bounding_box()
                if box:
                    await page.mouse.click(
                        box["x"] + box["width"] * 0.5,
                        box["y"] + box["height"] * 0.5,
                    )
                    return True
        except Exception:
            continue
        text_btn = page.get_by_text(confirm, exact=True).first
        try:
            if await text_btn.count() > 0 and await text_btn.is_visible():
                box = await text_btn.bounding_box()
                if box:
                    await page.mouse.click(
                        box["x"] + box["width"] * 0.5,
                        box["y"] + box["height"] * 0.5,
                    )
                    return True
        except Exception:
            continue
    return False


async def apply_ui_publish_time_filter(ctx: DouyinUiSession) -> str | None:
    """搜索列表页：点「筛选」→ 选「发布时间」→ 应用用户 days 对应选项。"""
    from app.platforms.search_filters import douyin_publish_time_ui_label, normalize_days

    if ctx.params.skip_search_filter:
        return None
    days = normalize_days(ctx.params.days)
    label = douyin_publish_time_ui_label(days)
    if not label or "/search/" not in (ctx.page.url or ""):
        return None

    page = ctx.page
    steps: list[str] = []
    ctx.state.pop("search_filter_verified", None)
    ctx.state.pop("search_filter_steps", None)

    await release_searchbar_focus(page)
    await _ui_pause(min_s=1.0, max_s=1.8)

    opened = False
    open_mode = ""
    for attempt in range(2):
        if attempt > 0:
            with contextlib.suppress(Exception):
                await page.keyboard.press("Escape")
            await _ui_pause(min_s=1.0, max_s=1.7)
        open_mode = await _open_search_filter_panel(ctx)
        steps.append(open_mode if attempt == 0 else f"{open_mode}_retry")
        if open_mode in {"already_open", "hover", "click"}:
            await _ui_pause(min_s=0.8, max_s=1.3)
            if await _wait_filter_panel_open(page, timeout_s=6.0):
                opened = True
                steps.append("panel_open")
                break
        if open_mode == "failed":
            await _ui_pause(min_s=0.9, max_s=1.5)
    if not opened:
        ctx.state["search_filter_steps"] = steps
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        return None

    await _ui_pause(min_s=0.9, max_s=1.6)
    if not await _click_publish_time_option(ctx, label):
        steps.append("option_miss")
        ctx.state["search_filter_steps"] = steps
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        return None
    steps.append(f"option={label}")

    if await _confirm_filter_panel(ctx):
        steps.append("confirm")
    else:
        steps.append("confirm_auto")
        await _ui_pause(min_s=1.0, max_s=1.8)

    await _wait_filter_panel_closed(page, timeout_s=8.0)
    if await _is_filter_panel_open(page):
        safe = await _search_results_safe_focus_point(page)
        with contextlib.suppress(Exception):
            await page.mouse.click(safe[0], safe[1])
        await _ui_pause(min_s=0.8, max_s=1.3)
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        await _wait_filter_panel_closed(page, timeout_s=5.0)
        if not await _is_filter_panel_open(page):
            steps.append("panel_dismiss")

    await _ui_pause(min_s=1.2, max_s=2.0)
    verified = await _verify_publish_time_filter_applied(page, label)
    weak_ok = any(str(s).startswith("option=") for s in steps) and not await _is_filter_panel_open(page)
    ctx.state["search_filter_verified"] = bool(verified)
    if verified:
        ctx.state["search_filter_steps"] = steps + ["verified=True"]
    elif weak_ok:
        steps.append("verified=weak")
        ctx.state["search_filter_steps"] = steps
    else:
        ctx.state["search_filter_steps"] = steps + ["verified=False"]
        with contextlib.suppress(Exception):
            await page.keyboard.press("Escape")
        return None

    ctx.state["search_filter_applied"] = label
    return label


async def run_search(ctx: DouyinUiSession) -> UiStepResult:
    keyword = ctx.params.keyword
    limit = ctx.params.content_limit
    api_items: dict[str, dict] = {}
    flags: dict[str, bool] = {"verify_check": False}
    needs_filter = _needs_ui_publish_filter(ctx)
    collect_api = {"enabled": False}

    if ctx.state.get("reuse_search_session"):
        reused = await reuse_search_results_if_ready(ctx, limit=limit)
        if reused is not None:
            return reused

    def _should_collect_response() -> bool:
        if needs_filter:
            return collect_api["enabled"]
        return bool(ctx.state.get("search_submitted"))

    async def on_response(resp) -> None:
        if not is_search_result_api(resp.url) or resp.status >= 400:
            return
        try:
            data = await resp.json()
        except Exception:
            return
        need = search_api_min_items(limit)
        outcome = analyze_search_api_response(data, min_items=need)
        mark_search_api_flags(flags, outcome)
        if outcome.ready:
            ctx.state["search_api_complete"] = True
            ctx.state["search_api_complete_reason"] = outcome.reason
        if not _should_collect_response():
            return
        for row in extract_aweme_items_from_json(data):
            api_items.setdefault(row["aweme_id"], row)
        if len(api_items) >= need:
            flags["api_complete"] = True
            flags["api_complete_reason"] = f"items={len(api_items)}"
            ctx.state["search_api_complete"] = True
            ctx.state["search_api_complete_reason"] = flags["api_complete_reason"]

    ctx.page.on("response", on_response)
    try:
        # ui_search_only：必须走搜索框，不复用当前搜索页
        if not _searchbar_only(ctx) and await _already_on_search_results(ctx, keyword):
            result = await _finalize_search_success(
                ctx,
                api_items=api_items,
                limit=limit,
                capture_method=f"{CAPTURE_METHOD_PREFIX}search_ui",
                diagnostic="复用当前搜索页",
                flags=flags,
            )
            if result.ok:
                return result

        if _searchbar_only(ctx):
            if not await _search_via_searchbar_ui(
                ctx,
                keyword,
                allow_scroll=not needs_filter,
            ):
                return UiStepResult(
                    ok=False,
                    error="E_SEARCH_UI",
                    diagnostic="未能通过搜索框完成搜索（禁止直接跳转搜索 URL）",
                )
            if not _on_search_results_url(ctx.page.url):
                return UiStepResult(
                    ok=False,
                    error="E_SEARCH_UI",
                    diagnostic=f"搜索提交后未进入结果页；当前 {ctx.page.url}",
                )
            if flags.get("verify_check"):
                return UiStepResult(ok=False, error="E_VERIFY_CHECK", diagnostic="verify_check")

            filter_label: str | None = None
            if needs_filter:
                filter_label = await apply_ui_publish_time_filter(ctx)
                api_items.clear()
                flags.pop("api_complete", None)
                flags.pop("api_complete_reason", None)
                flags.pop("api_explicit_empty", None)
                collect_api["enabled"] = True
                await _wait_post_filter_api(
                    ctx,
                    api_items,
                    flags=flags,
                    limit=limit,
                )
            else:
                await _wait_search_results(
                    ctx,
                    api_items=api_items,
                    flags=flags,
                    limit=limit,
                    keyword=keyword,
                    allow_direct_nav=False,
                    allow_scroll=True,
                )

            diagnostic = f"搜索框搜索完成 {ctx.page.url}"
            if flags.get("api_complete_reason"):
                diagnostic += f"；api={flags['api_complete_reason']}"
            if filter_label:
                verified = ctx.state.get("search_filter_verified")
                diagnostic += f"；发布时间={filter_label}"
                if verified:
                    diagnostic += "（已确认）"
                elif "verified=weak" in (ctx.state.get("search_filter_steps") or []):
                    diagnostic += "（弱确认：选项已点、浮层已关）"
                else:
                    diagnostic += "（未确认）"
            elif needs_filter:
                steps = ctx.state.get("search_filter_steps") or []
                if steps:
                    diagnostic += f"；筛选步骤={'>'.join(str(s) for s in steps)}"
                else:
                    diagnostic += "；筛选未生效"
            return await _finalize_search_success(
                ctx,
                api_items=api_items,
                limit=limit,
                capture_method=f"{CAPTURE_METHOD_PREFIX}search_ui",
                diagnostic=diagnostic,
                allow_scroll=not needs_filter,
                flags=flags,
            )

        if _on_search_results_page(ctx.page.url):
            ready = await _wait_search_results(
                ctx,
                api_items=api_items,
                flags=flags,
                limit=limit,
                keyword=keyword,
            )
            if flags.get("verify_check"):
                return UiStepResult(ok=False, error="E_VERIFY_CHECK", diagnostic="verify_check")
            if ready or "/jingxuan/search/" in (ctx.page.url or ""):
                return await _finalize_search_success(
                    ctx,
                    api_items=api_items,
                    limit=limit,
                    capture_method=f"{CAPTURE_METHOD_PREFIX}search_ui_direct",
                    diagnostic="精选搜索页已打开",
                    flags=flags,
                )

        search_input = await _search_input_locator(ctx.page, ctx.settings, tenant_id=ctx.tenant_id)
        if await search_input.count() == 0:
            return UiStepResult(ok=False, error="E_SEARCH_UI", diagnostic="未找到搜索框")

        await _human_type_one_per_second(ctx, search_input, keyword)
        await _submit_search(ctx, keyword=keyword)

        ready = await _wait_search_results(
            ctx,
            api_items=api_items,
            flags=flags,
            limit=limit,
            keyword=keyword,
        )
        if flags.get("verify_check"):
            return UiStepResult(ok=False, error="E_VERIFY_CHECK", diagnostic="verify_check")
        if not ready:
            await _navigate_to_search_results(ctx, keyword)
            ready = await _wait_search_results(
                ctx,
                api_items=api_items,
                flags=flags,
                limit=limit,
                keyword=keyword,
            )
        if not ready and not _on_search_results_page(ctx.page.url):
            return UiStepResult(
                ok=False,
                error="E_NO_CONTENT",
                diagnostic=f"搜索未完成或未返回视频；页 {ctx.page.url}",
            )
        return await _finalize_search_success(
            ctx,
            api_items=api_items,
            limit=limit,
            capture_method=f"{CAPTURE_METHOD_PREFIX}search_ui",
            diagnostic=f"搜索完成，页 {ctx.page.url}",
            flags=flags,
        )
    finally:
        try:
            ctx.page.remove_listener("response", on_response)
        except Exception:
            pass


async def run_searchbar_keyword_search(
    page,
    settings,
    *,
    tenant_id: str,
    account_id: str = "default",
    keyword: str,
    limit: int = 20,
    days: int | None = None,
    region: str | None = None,
) -> UiStepResult:
    """精选页搜索框输入关键词（skill_flow / ui_search_only 共用）。"""
    from app.services.ui_flow.params import parse_ui_flow_params
    from app.services.ui_flow.platforms.douyin.prepare_ui import run_prepare

    raw: dict = {
        "keyword": keyword,
        "content_limit": max(1, int(limit or 20)),
        "ui_search_only": True,
        "inline_ui_outreach": False,
        "platform_options": {"entry": "jingxuan"},
    }
    if days is not None:
        raw["days"] = days
    else:
        raw["skip_search_filter"] = True
    if region:
        raw["region"] = region
    params = parse_ui_flow_params(raw, platform="douyin")
    ctx = DouyinUiSession(
        settings=settings,
        tenant_id=tenant_id,
        account_id=account_id,
        params=params,
        page=page,
    )
    prepare = await run_prepare(ctx)
    if not prepare.ok:
        return UiStepResult(
            ok=False,
            error=prepare.error or "E_PAGE_NOT_READY",
            diagnostic=prepare.diagnostic or "精选页搜索框未就绪",
        )
    return await run_search(ctx)
