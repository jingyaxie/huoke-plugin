#!/usr/bin/env python3
"""对比抖音关键词搜索多种路径，找出可触发 general/search/single 的方案。"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

from app.core.antibot import human_click, human_delay, human_scroll, human_type
from app.core.config import get_settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.browser_runtime import BrowserRuntime


def _extract_videos(data: Any) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            aweme = node.get("aweme_info") if isinstance(node.get("aweme_info"), dict) else node
            if isinstance(aweme, dict):
                aweme_id = str(aweme.get("aweme_id") or "")
                if re.fullmatch(r"\d{8,22}", aweme_id) and aweme_id not in seen:
                    seen.add(aweme_id)
                    author = aweme.get("author") or {}
                    stats = aweme.get("statistics") or {}
                    videos.append(
                        {
                            "aweme_id": aweme_id,
                            "title": (aweme.get("desc") or "")[:60],
                            "author": author.get("nickname") or "",
                            "digg_count": stats.get("digg_count"),
                        }
                    )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return videos


async def _run_strategy(label: str, search_fn) -> dict[str, Any]:
    settings = get_settings()
    session = AgentBrowserSession(f"diag-{label}", "default", "douyin", settings, headless=False)
    runtime = BrowserRuntime(session, settings)
    report: dict[str, Any] = {"strategy": label, "ok": False}
    try:
        await runtime.ensure_page()
        await search_fn(runtime)
        page = runtime.session.page
        await human_delay(page, settings, tenant_id="default", profile="page_load")
        for _ in range(5):
            await human_scroll(page, settings, tenant_id="default")
            await human_delay(page, settings, tenant_id="default", profile="scroll")

        patterns = ["general/search/single", "search/item", "search/single"]
        matched_pattern = None
        for pattern in patterns:
            wait = await runtime.wait_api(url_contains=pattern, timeout_ms=8000)
            if wait.get("matched"):
                matched_pattern = pattern
                break

        apis = runtime.query_api(url_contains="search", limit=12, include_data=False)
        report["url"] = page.url
        report["title"] = await page.title()
        report["video_links"] = await page.locator('a[href*="/video/"]').count()
        report["api_paths"] = [item["path"] for item in apis.get("items", [])]
        report["matched_pattern"] = matched_pattern

        data_pattern = matched_pattern or "general/search"
        payload = runtime.query_api(url_contains=data_pattern, limit=3, include_data=True)
        videos: list[dict[str, Any]] = []
        for item in payload.get("items") or []:
            videos.extend(_extract_videos(item.get("data")))
        report["videos"] = videos[:5]
        report["ok"] = bool(videos) or report["video_links"] > 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await session.close()
    return report


async def strategy_home_searchbar(runtime: BrowserRuntime) -> None:
    page = runtime.session.page
    settings = runtime.settings
    await runtime.browse("https://www.douyin.com", warmup_first=True, scroll_rounds=1)
    inp = page.locator('[data-e2e="searchbar-input"]').first
    await human_click(page, inp, settings, tenant_id="default")
    await human_type(page, inp, "护肤", settings, tenant_id="default")
    await human_delay(page, settings, tenant_id="default", profile="action")
    await page.keyboard.press("Enter")


async def strategy_home_suggestion(runtime: BrowserRuntime) -> None:
    page = runtime.session.page
    settings = runtime.settings
    await runtime.browse("https://www.douyin.com", warmup_first=True, scroll_rounds=0)
    inp = page.locator('[data-e2e="searchbar-input"]').first
    await human_click(page, inp, settings, tenant_id="default")
    await human_type(page, inp, "护肤", settings, tenant_id="default", clear_first=False)
    await human_delay(page, settings, tenant_id="default", profile="action")
    sug = page.locator('[data-e2e="searchbar-sug-item"]').first
    if await sug.count():
        await human_click(page, sug, settings, tenant_id="default")
    else:
        await page.keyboard.press("Enter")


async def strategy_hot_searchbar(runtime: BrowserRuntime) -> None:
    page = runtime.session.page
    settings = runtime.settings
    await runtime.browse("https://www.douyin.com/hot", warmup_first=False, scroll_rounds=1)
    inp = page.locator('[data-e2e="searchbar-input"]').first
    await human_click(page, inp, settings, tenant_id="default")
    await human_type(page, inp, "护肤", settings, tenant_id="default")
    await page.keyboard.press("Enter")


async def strategy_jingxuan_searchbar(runtime: BrowserRuntime) -> None:
    page = runtime.session.page
    settings = runtime.settings
    await runtime.browse("https://www.douyin.com/jingxuan", warmup_first=False, scroll_rounds=1)
    inp = page.locator('[data-e2e="searchbar-input"]').first
    if await inp.count() == 0:
        raise RuntimeError("jingxuan 页未找到搜索框")
    await human_click(page, inp, settings, tenant_id="default")
    await human_type(page, inp, "护肤", settings, tenant_id="default")
    await page.keyboard.press("Enter")


STRATEGIES = {
    "home_searchbar": strategy_home_searchbar,
    "home_suggestion": strategy_home_suggestion,
    "hot_searchbar": strategy_hot_searchbar,
    "jingxuan_searchbar": strategy_jingxuan_searchbar,
}


async def main() -> int:
    names = list(STRATEGIES.keys())
    if len(sys.argv) > 1:
        names = [n for n in sys.argv[1:] if n in STRATEGIES]
    results = []
    for name in names:
        print(f"\n>>> 测试策略: {name}", flush=True)
        results.append(await _run_strategy(name, STRATEGIES[name]))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n通过: {ok}/{len(results)}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
