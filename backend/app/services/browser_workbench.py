from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "/").rstrip("/") or "/"
    return f"{parsed.scheme or 'https'}://{host}{path}"


def is_douyin_home_like(url: str) -> bool:
    u = (url or "").lower()
    if "douyin.com" not in u:
        return False
    path = (urlparse(u).path or "/").strip("/")
    return path in {"", "jingxuan", "home", "discover"}


def platform_home_url(session: Any) -> str | None:
    settings = session.settings
    if session.platform == "douyin":
        return settings.douyin_home_url
    if session.platform == "xiaohongshu":
        return settings.xhs_home_url
    if session.platform == "kuaishou":
        return settings.kuaishou_home_url
    return None


def should_skip_stable_goto(
    session: Any,
    target_url: str,
    *,
    force: bool = False,
) -> tuple[bool, str]:
    """稳定基座：同页/已在首页时不重复 goto，避免闪屏刷新。"""
    if force or not getattr(session, "stable_mode", False):
        return False, ""
    page = session._page
    if page is None:
        return False, ""
    current = (page.url or "").strip()
    if not current or current == "about:blank":
        return False, ""
    target = (target_url or "").strip()
    if not target:
        return False, ""
    if normalize_url(current) == normalize_url(target):
        return True, "same_url"
    home = platform_home_url(session)
    if home and normalize_url(target) == normalize_url(home) and is_douyin_home_like(current):
        return True, "already_on_home"
    return False, ""


async def bootstrap_stable_page(session: Any) -> dict[str, str]:
    """只启动一次浏览器；仅在 about:blank 时轻量进入首页，不 warmup 滚动。"""
    from app.platforms.douyin.human_guards import assert_not_browser_blocked

    if getattr(session, "bootstrapped", False) and session.is_started:
        page = session.page
        await assert_not_browser_blocked(page)
        return {"status": "reused", "url": page.url, "title": await page.title()}

    page = await session.ensure_started()
    url = (page.url or "").strip().lower()
    if url and url not in {"", "about:blank"} and "douyin.com" in url:
        await assert_not_browser_blocked(page)
        session.bootstrapped = True
        return {"status": "reused_on_page", "url": page.url, "title": await page.title()}
    if url in {"", "about:blank"}:
        home = platform_home_url(session)
        if home:
            await page.goto(home, wait_until="domcontentloaded", timeout=60000)
    await assert_not_browser_blocked(page)
    session.bootstrapped = True
    return {"status": "bootstrapped", "url": page.url, "title": await page.title()}
