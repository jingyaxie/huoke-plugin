"""Quick DOM probe for xhs top search on explore page."""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from app.platforms.xiaohongshu.search import XhsSearchTool, _TOP_SEARCH_SELECTORS, _TOP_SEARCH_INNER_SELECTORS, _SEARCH_SUBMIT_SELECTORS
from app.services.agent_browser_session import AgentBrowserSession


async def main() -> None:
    settings = get_settings()
    storage = os.environ.get(
        "STORAGE_ROOT",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage", "dev"),
    )
    state_path = f"{storage}/xiaohongshu/tenants/default/accounts/default/storage_state.json"
    tool = XhsSearchTool(settings, "default", account_id="default")
    browser = AgentBrowserSession("diag-xhs-search-dom", "default", "xiaohongshu", settings, headless=False)
    page = await browser.ensure_started()
    await page.goto(tool.entry_url(), wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(1000)

    probes = {}
    for sel in list(_TOP_SEARCH_SELECTORS) + list(_TOP_SEARCH_INNER_SELECTORS) + list(_SEARCH_SUBMIT_SELECTORS):
        loc = page.locator(sel).first
        cnt = await loc.count()
        box = await loc.bounding_box() if cnt else None
        vis = await loc.is_visible() if cnt else False
        probes[sel] = {"count": cnt, "box": box, "visible": vis}

    target = await tool._resolve_top_search_target(page)
    print("=== selectors ===")
    print(json.dumps(probes, ensure_ascii=False, indent=2))
    if target:
        inner = await target.evaluate("""el => {
          const all = [...el.querySelectorAll('*')].slice(0, 40).map(n => ({
            tag: n.tagName, id: n.id, cls: n.className?.toString?.()||'', ph: n.placeholder||'', ce: n.contentEditable, text: (n.innerText||'').slice(0,30)
          }));
          return {html: el.innerHTML.slice(0, 800), children: all};
        }""")
        print("=== inner ===", json.dumps(inner, ensure_ascii=False, indent=2))
        tag = await target.evaluate("el => ({tag: el.tagName, id: el.id, cls: el.className, ph: el.placeholder||'', ce: el.contentEditable})")
        print("=== target ===", tag)
        await tool._focus_top_search(page, target)
        await tool._type_into_top_search(page, target, "护肤")
        text = await tool._read_search_text(target)
        print("=== typed text ===", repr(text))

        box = await target.bounding_box()
        if box:
            x = box["x"] + box["width"] * 0.92
            y = box["y"] + box["height"] * 0.5
            print(f"=== click magnifier at ({x:.0f},{y:.0f}) ===")
            await page.mouse.click(x, y)
        await page.wait_for_timeout(5000)
        print("=== url after click ===", page.url)

        if "search_result" not in page.url:
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(5000)
            print("=== url after Enter ===", page.url)
    else:
        print("NO TARGET")


if __name__ == "__main__":
    asyncio.run(main())
