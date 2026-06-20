#!/usr/bin/env python3
"""快速探测抖音搜索路径。"""
from __future__ import annotations

import asyncio
import json
import re
import sys

from app.core.antibot import human_click, human_delay, human_type
from app.core.config import get_settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.browser_runtime import BrowserRuntime


async def try_path(entry_url: str, keyword: str = "护肤") -> dict:
    settings = get_settings()
    session = AgentBrowserSession("quick", "default", "douyin", settings, headless=False)
    runtime = BrowserRuntime(session, settings)
    result: dict = {"entry_url": entry_url}
    try:
        page = await runtime.ensure_page()
        await runtime.browse(entry_url, warmup_first=False, scroll_rounds=2)
        result["after_browse"] = {"url": page.url, "title": await page.title()}
        if "验证码" in result["after_browse"]["title"]:
            result["blocked"] = "captcha"
            return result

        inp = page.locator('[data-e2e="searchbar-input"]').first
        result["search_input_count"] = await inp.count()
        if await inp.count() == 0:
            result["blocked"] = "no_search_input"
            return result

        await human_click(page, inp, settings, tenant_id="default", timeout=15000)
        await human_type(page, inp, keyword, settings, tenant_id="default")
        await page.keyboard.press("Enter")
        await human_delay(page, settings, tenant_id="default", profile="page_load")
        for i in range(4):
            await page.mouse.wheel(0, 1200)
            await human_delay(page, settings, tenant_id="default", profile="scroll")

        result["after_search"] = {"url": page.url, "title": await page.title()}
        waits = {}
        for pattern in ("general/search/single", "search/item", "search/sug"):
            waits[pattern] = await runtime.wait_api(url_contains=pattern, timeout_ms=6000)
        result["wait_api"] = waits

        apis = runtime.query_api(url_contains="search", limit=10, include_data=False)
        result["api_paths"] = [x["path"] for x in apis.get("items", [])]
        result["video_links"] = await page.locator('a[href*="/video/"]').count()

        ids: list[str] = []
        for item in runtime.query_api(url_contains="general/search", limit=2, include_data=True).get("items", []):
            text = json.dumps(item.get("data") or {}, ensure_ascii=False)
            ids.extend(re.findall(r'"aweme_id"\s*:\s*"(\d+)"', text))
        if not ids:
            for item in runtime.query_api(url_contains="search/item", limit=2, include_data=True).get("items", []):
                text = json.dumps(item.get("data") or {}, ensure_ascii=False)
                ids.extend(re.findall(r'"aweme_id"\s*:\s*"(\d+)"', text))
        result["aweme_ids"] = list(dict.fromkeys(ids))[:8]
        result["ok"] = bool(result["aweme_ids"]) or result["video_links"] > 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await session.close()
    return result


async def main() -> None:
    paths = sys.argv[1:] or [
        "https://www.douyin.com/hot",
        "https://www.douyin.com",
        "https://www.douyin.com/jingxuan",
    ]
    results = []
    for url in paths:
        print(f"\n>>> {url}", flush=True)
        results.append(await try_path(url))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
