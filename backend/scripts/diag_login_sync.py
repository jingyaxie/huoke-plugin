#!/usr/bin/env python3
"""检查 storage_state 是否已注入系统 Chrome 上下文。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TENANT_ID = "default"
ACCOUNT_ID = "default"


async def main() -> int:
    from app.core.config import get_settings
    from app.platforms.douyin.session import DouyinSessionStore
    from app.services.playwright_pool import PlaywrightPool

    settings = get_settings()
    store = DouyinSessionStore(settings)
    login = store.login_status(TENANT_ID, account_id=ACCOUNT_ID)
    state = store.load(TENANT_ID, ACCOUNT_ID) or {}
    cookie_names = {
        c.get("name")
        for c in state.get("cookies", [])
        if isinstance(c, dict) and c.get("name")
    }

    report: dict = {
        "storage_root": str(settings.storage_root),
        "storage_state_path": login.get("storage_state_path"),
        "login_status": login.get("status"),
        "user_logged_in": login.get("user_logged_in"),
        "storage_cookie_count": len(state.get("cookies") or []),
        "has_sessionid": "sessionid" in cookie_names,
        "has_login_time": "login_time" in cookie_names,
    }

    pool = PlaywrightPool.get()
    try:
        async with pool.tenant_window(
            "douyin",
            TENANT_ID,
            store,
            settings,
            headless=False,
            persist_state=False,
            account_id=ACCOUNT_ID,
        ) as win:
            page = await win.open_tab(reuse_main=True)
            ctx_cookies = await win.context.cookies("https://www.douyin.com")
            ctx_names = {c.get("name") for c in ctx_cookies if c.get("name")}
            report["context_cookie_count"] = len(ctx_cookies)
            report["context_has_sessionid"] = "sessionid" in ctx_names
            report["context_has_login_time"] = "login_time" in ctx_names
            report["page_url"] = page.url
    finally:
        await pool.shutdown()

    ok = (
        report.get("login_status") == "ready"
        and report.get("context_has_sessionid")
        and report.get("context_cookie_count", 0) >= 10
    )
    report["ok"] = ok
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
