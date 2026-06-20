"""小红书搜索列表页「筛选」浮层：获焦/点击均会弹出，避免重复触发导致开关切换。"""
from __future__ import annotations

import asyncio
import contextlib
import random

from app.platforms.search_filters import normalize_days, xhs_publish_time_ui_label
from app.services.ui_flow.platforms.xiaohongshu.ui_session import XhsUiSession

_FILTER_PANEL_MARKERS = ("发布时间", "排序依据", "搜索范围", "笔记类型", "位置距离")

_FILTER_BUTTON_POINT_JS = """
() => {
  const isFilterNode = (n) => {
    const t = (n.textContent || '').replace(/\\s+/g, '');
    if (!t.includes('筛选') || t.length > 12) return false;
    const r = n.getBoundingClientRect();
    if (r.width < 16 || r.height < 12) return false;
    if (r.top < 40 || r.top > 240) return false;
    if (r.left < window.innerWidth * 0.45) return false;
    return true;
  };
  const nodes = [...document.querySelectorAll('span, div, button, a, label')];
  const candidates = nodes.filter(isFilterNode);
  candidates.sort((a, b) => {
    const ra = a.getBoundingClientRect();
    const rb = b.getBoundingClientRect();
    const scoreA = ra.left * 2 + ra.width * ra.height;
    const scoreB = rb.left * 2 + rb.width * rb.height;
    return scoreB - scoreA;
  });
  const btn = candidates[0];
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2, top: r.top, left: r.left, height: r.height, width: r.width };
}
"""

_FILTER_PANEL_OPEN_JS = """
() => {
  const markers = ['发布时间', '排序依据', '搜索范围', '笔记类型', '位置距离'];
  const blocks = [...document.querySelectorAll('div, section, aside, ul')];
  for (const el of blocks) {
    const r = el.getBoundingClientRect();
    if (r.height < 72 || r.width < 160) continue;
    if (r.top < 72 || r.top > window.innerHeight * 0.78) continue;
    const text = (el.innerText || '').slice(0, 800);
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


def _on_search_results_page(url: str | None) -> bool:
    return "search_result" in (url or "")


def needs_ui_publish_filter(ctx: XhsUiSession) -> bool:
    if ctx.params.skip_search_filter:
        return False
    return bool(xhs_publish_time_ui_label(normalize_days(ctx.params.days)))


async def _ui_pause(*, min_s: float = 0.8, max_s: float = 1.6) -> None:
    await asyncio.sleep(random.uniform(min_s, max_s))


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


async def release_searchbar_focus(page) -> None:
    with contextlib.suppress(Exception):
        await page.evaluate(
            """() => {
              const el = document.querySelector('#search-input-in-feeds textarea, #search-input-in-feeds input');
              if (el) el.blur();
              const active = document.activeElement;
              if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {
                active.blur();
              }
            }"""
        )


async def _search_results_safe_focus_point(page) -> tuple[float, float]:
    vp = page.viewport_size or {"width": 1440, "height": 1200}
    return float(vp["width"] * 0.35), float(vp["height"] * 0.42)


async def _filter_button_point(page) -> dict | None:
    try:
        point = await page.evaluate(_FILTER_BUTTON_POINT_JS)
        if isinstance(point, dict):
            return point
    except Exception:
        pass
    try:
        loc = page.get_by_text("筛选", exact=True).first
        if await loc.count():
            box = await loc.bounding_box()
            if box and box.get("width", 0) > 8:
                return {
                    "x": box["x"] + box["width"] / 2,
                    "y": box["y"] + box["height"] / 2,
                    "top": box["y"],
                    "left": box["x"],
                    "height": box["height"],
                    "width": box["width"],
                }
    except Exception:
        pass
    return None


async def _open_search_filter_panel(ctx: XhsUiSession) -> str:
    """打开筛选浮层。筛选按钮 hover/聚焦/点击都会触发浮层，避免重复触发导致开关切换。"""
    page = ctx.page
    if await _is_filter_panel_open(page):
        return "already_open"

    point = await _filter_button_point(page)
    if not point:
        return "failed"

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


async def _click_publish_time_option(ctx: XhsUiSession, label: str) -> bool:
    page = ctx.page
    if not await _is_filter_panel_open(page):
        return False
    await _ui_pause(min_s=0.8, max_s=1.3)
    try:
        point = await page.evaluate(
            """(label) => {
              const markers = ['发布时间', '排序依据', '搜索范围', '笔记类型', '位置距离'];
              const blocks = [...document.querySelectorAll('div, section, aside, ul')];
              let panel = null;
              for (const el of blocks) {
                const r = el.getBoundingClientRect();
                if (r.height < 72 || r.width < 160) continue;
                if (r.top < 72 || r.top > window.innerHeight * 0.78) continue;
                const text = (el.innerText || '').slice(0, 800);
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


async def _confirm_filter_panel(ctx: XhsUiSession) -> bool:
    page = ctx.page
    if not await _is_filter_panel_open(page):
        return False
    await _ui_pause(min_s=0.7, max_s=1.2)
    for confirm in ("收起", "确定", "完成", "应用"):
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


async def apply_ui_publish_time_filter(ctx: XhsUiSession) -> str | None:
    """搜索列表页：点「筛选」→ 选「发布时间」→ 收起浮层。"""
    if ctx.params.skip_search_filter:
        return None
    days = normalize_days(ctx.params.days)
    label = xhs_publish_time_ui_label(days)
    if not label or not _on_search_results_page(ctx.page.url):
        return None

    page = ctx.page
    steps: list[str] = []
    ctx.state.pop("search_filter_verified", None)
    ctx.state.pop("search_filter_steps", None)

    await release_searchbar_focus(page)
    with contextlib.suppress(Exception):
        await page.evaluate("window.scrollTo(0, 0)")
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

    ctx.state["search_filter_steps"] = steps
    ctx.state["search_filter_applied"] = label
    ctx.state["search_filter_verified"] = not await _is_filter_panel_open(page)
    return label


async def is_filter_panel_open(page) -> bool:
    return await _is_filter_panel_open(page)
