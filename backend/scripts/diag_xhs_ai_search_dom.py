"""Probe note card DOM on xhs search_result / search_result_ai page."""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from app.platforms.xiaohongshu.search import XhsSearchTool
from app.services.agent_browser_session import AgentBrowserSession


PROBE_JS = """
() => {
  const links = [...document.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/item/"]')];
  const samples = links.slice(0, 12).map((a) => {
    const r = a.getBoundingClientRect();
    return {
      href: (a.href || a.getAttribute('href') || '').slice(0, 160),
      cls: (a.className || '').toString().slice(0, 80),
      w: r.width, h: r.height, y: r.y,
      parent: (a.parentElement?.className || '').toString().slice(0, 60),
    };
  });
  const cardSels = [
    'section.note-item', '[class*="note-item"]', '[class*="NoteItem"]',
    '[class*="feed-item"]', '[class*="feeds"]', '[class*="search-note"]',
    '[class*="note-card"]', '[class*="card"]',
  ];
  const counts = {};
  for (const sel of cardSels) counts[sel] = document.querySelectorAll(sel).length;
  return { url: location.href, title: document.title, counts, samples };
}
"""


async def main() -> None:
    settings = get_settings()
    tool = XhsSearchTool(settings, "default", account_id="default")
    browser = AgentBrowserSession("diag-ai-search", "default", "xiaohongshu", settings, headless=False)
    page = await browser.ensure_started()
    await page.goto(tool.entry_url(), wait_until="domcontentloaded")
    ok = await tool._trigger_searchbar(page, "护肤")
    print("search ok", ok, "url", page.url)
    await page.wait_for_timeout(3000)
    info = await page.evaluate(PROBE_JS)
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
