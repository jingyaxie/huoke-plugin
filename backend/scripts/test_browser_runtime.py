#!/usr/bin/env python3
"""用 BrowserRuntime 底层能力测试抖音/小红书接口拦截（无业务解析）。"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from app.core.config import get_settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.browser_runtime import BrowserRuntime


def _preview_data(data: Any, max_keys: int = 8) -> Any:
    if isinstance(data, dict):
        keys = list(data.keys())[:max_keys]
        return {k: _preview_data(data[k], max_keys) for k in keys}
    if isinstance(data, list):
        return [_preview_data(data[0], max_keys)] if data else []
    if isinstance(data, str) and len(data) > 120:
        return data[:120] + "…"
    return data


def _print_case(title: str, result: dict[str, Any]) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


async def test_platform(
    platform: str,
    *,
    browse_url: str,
    api_pattern: str,
    fallback_patterns: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    session = AgentBrowserSession(
        session_id=f"test-{platform}",
        tenant_id="default",
        platform=platform,
        settings=settings,
    )
    runtime = BrowserRuntime(session, settings)
    report: dict[str, Any] = {"platform": platform, "ok": False}

    try:
        browse = await runtime.browse(
            browse_url,
            warmup_first=True,
            scroll_rounds=3,
        )
        report["browse"] = browse

        wait = await runtime.wait_api(url_contains=api_pattern, timeout_ms=20000)
        report["wait_api"] = wait

        pattern = api_pattern
        if not wait.get("matched") and fallback_patterns:
            for fb in fallback_patterns:
                wait_fb = await runtime.wait_api(url_contains=fb, timeout_ms=8000)
                report[f"wait_api_{fb}"] = wait_fb
                if wait_fb.get("matched"):
                    pattern = fb
                    break

        data = runtime.query_api(url_contains=pattern, limit=2, include_data=True)
        items = data.get("items") or []
        report["api"] = {
            "pattern": pattern,
            "count": data.get("count"),
            "paths": [i.get("path") for i in items],
            "summaries": [i.get("summary") for i in items],
        }
        if items:
            first = items[0]
            report["api"]["first_status"] = first.get("status")
            report["api"]["first_data_preview"] = _preview_data(first.get("data"))
            report["ok"] = first.get("data") is not None
        else:
            all_paths = [e.path for e in runtime.capture.entries[-30:]]
            report["recent_api_paths"] = all_paths

        info = await session.page_info()
        report["page"] = {"url": info.get("url"), "title": info.get("title")}
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await session.close()

    return report


async def main() -> int:
    cases = [
        {
            "title": "抖音热榜 — channel/hotspot",
            "platform": "douyin",
            "browse_url": "https://www.douyin.com/hot",
            "api_pattern": "channel/hotspot",
            "fallback_patterns": ["hot/search/list", "hotspot"],
        },
        {
            "title": "小红书发现页 — homefeed",
            "platform": "xiaohongshu",
            "browse_url": "https://www.xiaohongshu.com/explore",
            "api_pattern": "homefeed",
            "fallback_patterns": ["feed", "explore"],
        },
    ]

    results: list[dict[str, Any]] = []
    for case in cases:
        print(f"\n>>> 开始测试: {case['title']}")
        result = await test_platform(
            case["platform"],
            browse_url=case["browse_url"],
            api_pattern=case["api_pattern"],
            fallback_patterns=case.get("fallback_patterns"),
        )
        results.append(result)
        _print_case(case["title"], result)

    passed = sum(1 for r in results if r.get("ok"))
    print(f"\n{'=' * 60}")
    print(f"结果: {passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
