from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page

from app.core.antibot import human_delay
from app.core.config import Settings
from app.platforms.douyin.session import (
    DouyinSessionStore,
    REQUIRED_LOGIN_COOKIES,
    USER_LOGIN_MARKERS,
)


class HumanBrowseGuardError(RuntimeError):
    """真人模拟链路前置检查未通过（登录态或页面未就绪）。"""


_STAGE_HINTS: dict[str, tuple[tuple[str, str], ...]] = {
    "home": (
        ('[data-e2e="searchbar-input"]', "搜索框"),
    ),
    "search": (
        ('a[href*="/video/"]', "视频搜索结果"),
        ('[data-e2e="search-card-video"]', "视频封面"),
    ),
    "video": (
        ('[data-e2e="comment-item"]', "评论列表"),
        ('[class*="CommentItem"]', "评论条目"),
        ('[data-e2e="feed-comment-icon"]', "评论入口"),
    ),
    "feed": (
        ('text=全部评论', "评论侧栏"),
        ('[data-e2e="comment-item"]', "评论条目"),
        ('[class*="CommentItem"]', "评论条目"),
    ),
    "comment": (
        ('text=全部评论', "评论侧栏"),
        ('[data-e2e="comment-item"]', "评论条目"),
        ('[class*="CommentItem"]', "评论条目"),
    ),
    "reply": (
        ('[data-e2e="comment-reply"]', "回复按钮"),
        ('button:has-text("回复")', "回复按钮"),
        ('[data-e2e="comment-input"]', "回复输入框"),
        ('div[contenteditable="true"]', "回复输入框"),
    ),
    "profile": (
        ('[data-e2e="user-info-follow"]', "关注按钮"),
        ('button:has-text("关注")', "关注按钮文案"),
    ),
}

_LOGIN_WALL_SELECTORS = (
    "text=扫码登录",
    "text=登录后查看更多",
    '[data-e2e="login-button"]',
)

_BLOCKED_HOST_MARKERS = ("so-landing.douyin.com",)


def is_blocked_douyin_host(url: str) -> bool:
    """抖音将自动化有头浏览器导向 sinkhole 域时，主 tab 会落在此类 host。"""
    host = (urlparse((url or "").strip()).hostname or "").lower()
    return any(marker in host for marker in _BLOCKED_HOST_MARKERS)


async def is_browser_blocked_page(page: Page) -> tuple[bool, str]:
    url = (page.url or "").strip()
    if is_blocked_douyin_host(url):
        return True, "so_landing_redirect"
    try:
        title = ((await page.title()) or "").strip().lower()
        if title in {"404 not found", "404"}:
            return True, "http_404"
    except Exception:
        pass
    return False, ""


async def assert_not_browser_blocked(page: Page) -> None:
    blocked, reason = await is_browser_blocked_page(page)
    if not blocked:
        return
    if reason == "so_landing_redirect":
        raise HumanBrowseGuardError(
            "当前页面被导向 so-landing.douyin.com（抖音识别为自动化浏览器）。"
            "请使用系统 Chrome（ANTIBOT_BROWSER_CHANNEL=chrome），并确保已登录抖音网页版。"
        )
    raise HumanBrowseGuardError(
        "当前页面返回 404，浏览器可能被抖音拦截。"
        "请使用系统 Chrome（ANTIBOT_BROWSER_CHANNEL=chrome），并检查登录态。"
    )


async def is_captcha_page(page: Page) -> bool:
    try:
        title = (await page.title()) or ""
        if "验证码中间页" in title:
            return True
        body_text = await page.locator("body").inner_text(timeout=1500)
        return "验证码中间页" in body_text
    except Exception:
        return False


async def _wait_page_loaded(page: Page, *, timeout_ms: int = 30000) -> None:
    await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=min(8000, timeout_ms))
    except Exception:
        pass


async def _live_cookie_names(page: Page) -> set[str]:
    try:
        return {c.get("name") for c in await page.context.cookies() if c.get("name")}
    except Exception:
        return set()


async def _detect_login_wall(page: Page) -> bool:
    for selector in _LOGIN_WALL_SELECTORS:
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _wait_stage_markers(page: Page, stage: str, *, timeout_ms: int = 20000) -> str:
    markers = _STAGE_HINTS.get(stage, ())
    if not markers:
        return "page_loaded"
    last_error = "页面关键元素未出现"
    per_selector = max(3000, timeout_ms // max(len(markers), 1))
    for selector, label in markers:
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=per_selector)
            return label
        except Exception as exc:
            last_error = f"{label}未加载完成（{type(exc).__name__}）"
    if stage == "video" and "/video/" in (page.url or ""):
        return "video_url"
    if stage == "feed":
        try:
            body = await page.locator("body").inner_text(timeout=2000)
            if "全部评论" in body:
                return "feed_sidebar"
        except Exception:
            pass
    if stage == "search" and "/search/" in (page.url or ""):
        return "search_url"
    raise HumanBrowseGuardError(last_error)


def _storage_login_status(
    store: DouyinSessionStore,
    tenant_id: str,
    account_id: str,
) -> dict[str, Any]:
    state = store.load(tenant_id, account_id)
    if not store.is_ready(state):
        raise HumanBrowseGuardError("未检测到有效登录 Cookie，请先登录抖音。")
    cookie_names = {c.get("name") for c in (state or {}).get("cookies", []) if isinstance(c, dict)}
    logged_in = bool(cookie_names & USER_LOGIN_MARKERS)
    return {
        "storage_ready": True,
        "logged_in": logged_in,
        "session_mode": "logged_in" if logged_in else "guest",
    }


async def assert_douyin_human_ready(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str = "default",
    store: DouyinSessionStore | None = None,
    stage: str = "home",
    goto_home: bool = False,
    page_load_timeout_ms: int = 30000,
) -> dict[str, Any]:
    """真人操作前门禁：存储登录态 → 打开页面 → 页面加载 → 在线 Cookie/UI 校验。"""
    session_store = store or DouyinSessionStore(settings)
    storage = _storage_login_status(session_store, tenant_id, account_id)

    if goto_home:
        await page.goto(settings.douyin_home_url, wait_until="domcontentloaded", timeout=page_load_timeout_ms)
        await human_delay(page, settings, tenant_id=tenant_id, profile="page_load")
    else:
        await _wait_page_loaded(page, timeout_ms=page_load_timeout_ms)

    await assert_not_browser_blocked(page)

    if await is_captcha_page(page):
        raise HumanBrowseGuardError(
            "当前页面处于验证码中间页，请先在可见浏览器中完成人机验证后再继续。"
        )

    live_names = await _live_cookie_names(page)
    if not live_names & REQUIRED_LOGIN_COOKIES:
        raise HumanBrowseGuardError(
            "浏览器会话中未检测到抖音登录 Cookie，请重新扫码登录后再操作。"
        )

    if await _detect_login_wall(page):
        raise HumanBrowseGuardError(
            "页面仍显示登录入口，当前会话未真正登录，请完成扫码登录后再继续。"
        )

    marker = await _wait_stage_markers(page, stage, timeout_ms=page_load_timeout_ms)
    live_logged_in = bool(live_names & USER_LOGIN_MARKERS)
    return {
        "ok": True,
        "stage": stage,
        "marker": marker,
        "page_url": page.url,
        "session_mode": "logged_in" if live_logged_in else storage.get("session_mode", "guest"),
        "storage_ready": True,
    }
