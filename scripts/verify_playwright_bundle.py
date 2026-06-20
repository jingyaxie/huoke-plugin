#!/usr/bin/env python3
"""[DEPRECATED] 旧版 Playwright bundle 冒烟测试。瘦壳架构不再打包 Playwright。"""
from __future__ import annotations

import os
import sys


def main() -> int:
    channel = (os.environ.get("ANTIBOT_BROWSER_CHANNEL") or "chrome").strip() or "chrome"
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=channel, headless=True)
            browser.close()
    except Exception as exc:
        print(
            f"无法通过 Playwright channel={channel!r} 启动系统浏览器: {exc}",
            file=sys.stderr,
        )
        print("请安装 Google Chrome，或设置 ANTIBOT_BROWSER_CHANNEL 指向本机 Chromium。", file=sys.stderr)
        return 1

    print(f"system browser launch ok (channel={channel})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
