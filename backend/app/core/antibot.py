from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import platform as py_platform
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright

from app.schemas.antibot import (
    AntibotDelayProfileOut,
    AntibotGlobalConfigOut,
    TenantAntibotConfigOut,
    TenantAntibotOverrideOut,
)
if TYPE_CHECKING:
    from app.services.tenant_antibot_store import TenantAntibotStore
    from app.core.config import Settings
    from app.platforms.session_store import PlatformSessionStore

DEFAULT_MAC_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_LINUX_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_WIN_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_USER_AGENT = DEFAULT_MAC_USER_AGENT

STEALTH_VERSION = "v4"

# 变更浏览器启动参数时递增，触发已有浏览器会话自动重建
BROWSER_RENDER_EPOCH = 4

_last_mouse_pos: dict[int, tuple[float, float]] = {}
_BASE_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]
_LINUX_LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox"]

_ALLOWED_NAV_SCHEMES = frozenset(
    {"http", "https", "about", "data", "blob", "chrome", "chrome-extension", "file", "javascript", "ws", "wss"}
)
_BLOCKED_PROTOCOL_SCHEMES = (
    "snssdk1128",
    "snssdk",
    "aweme",
    "bytedance",
    "douyin",
    "tiktok",
    "sslocal",
    "sslocalb",
    "sslocalc",
    "live",
    "tt",
    "intent",
    "market",
    "xhsdiscover",
    "xhs",
    "xiaohongshu",
    "kwai",
    "kuaishou",
    "bitbrowser",
)

_LINUX_POLICY_DIR = Path("/etc/huoke/chrome-policies/managed")

_PROTOCOL_LAUNCH_ARGS = (
    "--disable-features=ExternalProtocolPrompt,ExternalProtocolDialogShowAlwaysOpenCheckbox",
)


def _linux_protocol_launch_args() -> list[str]:
    args = list(_PROTOCOL_LAUNCH_ARGS)
    if _LINUX_POLICY_DIR.is_dir():
        args.append(f"--policy-path={_LINUX_POLICY_DIR}")
    return args

_EXTERNAL_PROTOCOL_GUARD_JS = """
(() => {
  const allowed = new Set(['http','https','about','data','blob','file','javascript','chrome','ws','wss']);
  const isBlocked = (url) => {
    if (!url || typeof url !== 'string') return false;
    const m = url.match(/^([a-z][a-z0-9+.-]*):/i);
    if (!m) return false;
    return !allowed.has(m[1].toLowerCase());
  };
  const blockNav = (url) => {
    if (!isBlocked(url)) return false;
    return true;
  };
  const isTrackingUrl = (url) => {
    if (!url || typeof url !== 'string') return false;
    try {
      const u = new URL(url, location.href);
      const h = (u.hostname || '').toLowerCase();
      if (!h || h === (location.hostname || '').toLowerCase()) return false;
      if (/^lf[\w-]*\.douyin\.com$/i.test(h)) return true;
      if (/^(mon|mcs|log)\./i.test(h)) return true;
      if (/\.zijieapi\.com$/i.test(h)) return true;
      return false;
    } catch (e) {
      return false;
    }
  };
  const isPopupOnlyUrl = (url) => {
    if (!url || typeof url !== 'string') return true;
    const raw = url.trim();
    if (!raw || raw === 'about:blank') return true;
    return isTrackingUrl(url);
  };
  const safeSameTabNav = (url) => {
    if (!url || blockNav(url) || isPopupOnlyUrl(url)) return;
    try { window.location.assign(url); } catch (e) {}
  };
  const origOpen = window.open;
  window.open = function(url, ...rest) {
    if (blockNav(url)) return null;
    if (isPopupOnlyUrl(url)) return null;
    if (url && typeof url === 'string') {
      safeSameTabNav(url);
      return window;
    }
    return null;
  };
  const origAssign = window.location.assign.bind(window.location);
  window.location.assign = function(url) {
    if (blockNav(url) || isPopupOnlyUrl(url)) return;
    return origAssign(url);
  };
  const origReplace = window.location.replace.bind(window.location);
  window.location.replace = function(url) {
    if (blockNav(url) || isPopupOnlyUrl(url)) return;
    return origReplace(url);
  };
  const normalizeFormTarget = (form) => {
    if (!form) return;
    const target = (form.getAttribute('target') || '').toLowerCase();
    if (target === '_blank' || target === '_new') {
      form.setAttribute('target', '_self');
    }
  };
  document.addEventListener('submit', (ev) => {
    normalizeFormTarget(ev.target);
  }, true);
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter') return;
    const el = ev.target;
    if (!el || !el.closest) return;
    normalizeFormTarget(el.closest('form'));
  }, true);
  document.addEventListener('click', (ev) => {
    const el = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
    if (!el) return;
    const href = el.getAttribute('href') || '';
    const target = (el.getAttribute('target') || '').toLowerCase();
    const newTabGesture = ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button === 1;
    if (target === '_blank' || target === '_new' || newTabGesture) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      safeSameTabNav(href);
      return;
    }
    if (blockNav(href) || isPopupOnlyUrl(href)) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }
  }, true);
  const redirectLinkToSameTab = (ev) => {
    const el = ev.target && ev.target.closest ? ev.target.closest('a[href]') : null;
    if (!el) return;
    const href = el.getAttribute('href') || '';
    const target = (el.getAttribute('target') || '').toLowerCase();
    if (target === '_blank' || target === '_new' || ev.button === 1) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      safeSameTabNav(href);
    }
  };
  document.addEventListener('auxclick', redirectLinkToSameTab, true);
})();
"""


def _is_external_protocol_url(url: str) -> bool:
    if not url or "://" not in url:
        return False
    scheme = url.split("://", 1)[0].lower()
    return scheme not in _ALLOWED_NAV_SCHEMES


_CHROME_SINGLETON_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def clear_stale_chrome_profile_locks(profile_dir: Path) -> None:
    """Remove stale Chromium singleton files before launching a persistent profile.

    Docker bind mounts and hot reload can leave broken SingletonLock symlinks that
    block the next launch with ProcessSingleton errors. Avoid path.exists() here —
    broken symlinks on bind mounts can raise OSError EINVAL.
    """
    for name in _CHROME_SINGLETON_FILES:
        path = profile_dir / name
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def terminate_chrome_for_profile(profile_dir: Path) -> None:
    """Best-effort kill Chrome processes still holding this user-data-dir."""
    try:
        resolved = str(profile_dir.resolve())
    except OSError:
        return
    needle = f"--user-data-dir={resolved}"
    if py_platform.system() not in {"Darwin", "Linux"}:
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["pkill", "-f", needle],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )


def _desktop_native_chrome_launch_args() -> list[str]:
    """macOS 桌面端系统 Chrome + 专用 Profile：抑制「个人资料出错」类弹窗。"""
    return [
        "--no-first-run",
        "--disable-sync",
        "--no-default-browser-check",
        "--disable-restore-session-state",
        "--disable-signin-promo",
        "--disable-features=SignInProfileCreation,SigninIntercept,AccountConsistency,ExternalProtocolHandler",
    ]


def seed_profile_protocol_prefs(profile_dir: Path) -> None:
    """在 persistent profile 中静默拒绝外部协议，避免 Linux xdg-open 弹窗。"""
    local_state_path = profile_dir / "Local State"
    data: dict = {}
    if local_state_path.exists():
        try:
            data = json.loads(local_state_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    handler = data.setdefault("protocol_handler", {})
    excluded = handler.setdefault("excluded_schemes", {})
    for scheme in _BLOCKED_PROTOCOL_SCHEMES:
        excluded[scheme] = True
    try:
        local_state_path.parent.mkdir(parents=True, exist_ok=True)
        local_state_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    prefs_path = profile_dir / "Default" / "Preferences"
    prefs: dict = {}
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        except Exception:
            prefs = {}
    pref_handler = prefs.setdefault("protocol_handler", {})
    pref_excluded = pref_handler.setdefault("excluded_schemes", {})
    for scheme in _BLOCKED_PROTOCOL_SCHEMES:
        pref_excluded[scheme] = True
    custom_handlers = prefs.setdefault("custom_handlers", {})
    custom_handlers["enabled"] = False
    try:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


async def install_dialog_auto_dismiss(context: BrowserContext) -> None:
    async def _dismiss(dialog) -> None:
        try:
            await dialog.dismiss()
        except Exception:
            pass

    def _bind_page(page: Page) -> None:
        page.on("dialog", lambda dialog: asyncio.create_task(_dismiss(dialog)))

    context.on("page", _bind_page)
    for page in context.pages:
        _bind_page(page)


async def install_external_protocol_guard(context: BrowserContext) -> None:
    async def _route_handler(route) -> None:
        if _is_external_protocol_url(route.request.url):
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    await context.route("**/*", _route_handler)
    await context.add_init_script(_EXTERNAL_PROTOCOL_GUARD_JS)

_DELAY_PROFILES: dict[str, tuple[float, float]] = {
    "default": (1.0, 1.0),
    "page_load": (1.4, 2.0),
    "scroll": (0.7, 1.2),
    "action": (0.4, 0.9),
    "poll": (0.9, 1.1),
    "between_items": (1.0, 1.6),
    "warmup": (1.2, 1.8),
    "fast": (0.12, 0.28),
}

class LoginRequiredError(RuntimeError):
    """Raised when a crawl is attempted without a valid platform login session."""


@lru_cache
def _stealth_init_script_template() -> str:
    path = Path(__file__).with_name("stealth_init.js")
    return path.read_text(encoding="utf-8")


def launch_args(settings: Settings | None = None, *, headless: bool = True) -> list[str]:
    if settings is not None and uses_native_system_chrome(settings, headless=headless):
        if settings.desktop_mode:
            return _desktop_native_chrome_launch_args()
        return []
    args = list(_BASE_LAUNCH_ARGS)
    if sys.platform.startswith("linux"):
        args.extend(_LINUX_LAUNCH_ARGS)
        args.extend(_linux_protocol_launch_args())
    elif py_platform.system() == "Darwin":
        args.extend([
            "--no-first-run",
            "--disable-sync",
            "--no-default-browser-check",
            "--disable-restore-session-state",
            "--disable-features=ExternalProtocolHandler,TranslateUI",
        ])
    return args


def browser_channel(settings: Settings) -> str | None:
    channel = (settings.antibot_browser_channel or "").strip()
    return channel or None


def uses_native_system_chrome(settings: Settings, *, headless: bool) -> bool:
    """有头 + channel 指向本机 Chrome：正常人浏览，不注入 antibot，由 Skill 驱动画面上操作。"""
    if headless:
        return False
    return bool(browser_channel(settings))


def launch_kwargs(settings: Settings, *, headless: bool) -> dict:
    kwargs: dict = {"headless": headless, "args": launch_args(settings, headless=headless)}
    channel = browser_channel(settings)
    if channel:
        kwargs["channel"] = channel
    if uses_native_system_chrome(settings, headless=headless):
        # 系统 Chrome：去掉自动化标记参数，减少异常 tab/焦点行为
        ignored = ["--enable-automation"]
        # macOS 有头：Playwright 默认 --no-startup-window 会抑制首窗，用户看不到浏览器
        if not headless and py_platform.system() == "Darwin":
            ignored.append("--no-startup-window")
        kwargs["ignore_default_args"] = ignored
    return kwargs


def fingerprint_platform(settings: Settings) -> str:
    mode = (settings.antibot_fingerprint_platform or "mac").strip().lower()
    if mode == "auto":
        system = py_platform.system()
        if system == "Darwin":
            return "mac"
        if system == "Windows":
            return "win"
        return "linux"
    if mode in {"mac", "darwin", "macos"}:
        return "mac"
    if mode in {"win", "windows"}:
        return "win"
    return "linux"


def default_user_agent_for_settings(settings: Settings) -> str:
    platform = fingerprint_platform(settings)
    if platform == "mac":
        return DEFAULT_MAC_USER_AGENT
    if platform == "win":
        return DEFAULT_WIN_USER_AGENT
    return DEFAULT_LINUX_USER_AGENT


def _chrome_version_binaries() -> list[list[str]]:
    commands = [
        ["google-chrome", "--version"],
        ["google-chrome-stable", "--version"],
        ["chromium", "--version"],
        ["chromium-browser", "--version"],
    ]
    if py_platform.system() == "Darwin":
        commands.insert(
            0,
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
        )
    cache_root = Path.home() / ".cache" / "ms-playwright"
    if cache_root.exists():
        for pattern in (
            "chromium-*/chrome-linux/chrome",
            "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
            "chrome-*/chrome-linux/chrome",
            "chrome-*/chrome-mac/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ):
            for binary in sorted(cache_root.glob(pattern)):
                commands.append([str(binary), "--version"])
    return commands


@lru_cache
def detected_chrome_major_version() -> str | None:
    for cmd in _chrome_version_binaries():
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=5)
        except Exception:
            continue
        match = re.search(r"(?:Chrome|Chromium)\s+(\d+)", output)
        if match:
            return match.group(1)
    return None


def _sync_chrome_version_in_ua(ua: str) -> str:
    major = detected_chrome_major_version()
    if not major:
        return ua
    return re.sub(r"Chrome/\d+(?:\.\d+)*", f"Chrome/{major}.0.0.0", ua)


def user_agent(settings: Settings) -> str:
    custom = (settings.antibot_user_agent or "").strip()
    if custom:
        return _sync_chrome_version_in_ua(custom)
    return _sync_chrome_version_in_ua(default_user_agent_for_settings(settings))


def chrome_major_from_ua(ua: str) -> str:
    match = re.search(r"Chrome/(\d+)", ua)
    if match:
        return match.group(1)
    return detected_chrome_major_version() or "131"


def client_hints_headers(settings: Settings) -> dict[str, str]:
    ua = user_agent(settings)
    major = chrome_major_from_ua(ua)
    is_mac = fingerprint_platform(settings) == "mac"
    platform_label = '"macOS"' if is_mac else '"Linux"'
    return {
        "sec-ch-ua": f'"Google Chrome";v="{major}", "Chromium";v="{major}", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": platform_label,
    }


def viewport(settings: Settings, *, headless: bool = True) -> dict[str, int]:
    return {"width": settings.antibot_viewport_width, "height": settings.antibot_viewport_height}


def stealth_fingerprint_meta(settings: Settings) -> dict:
    major = chrome_major_from_ua(user_agent(settings))
    is_mac = fingerprint_platform(settings) == "mac"
    if is_mac:
        return {
            "languages": ["zh-CN", "zh", "en-US", "en"],
            "platform": "MacIntel",
            "hardware_concurrency": 8,
            "device_memory": 8,
            "max_touch_points": 0,
            "webgl_vendor": "Intel Inc.",
            "webgl_renderer": "Intel Iris OpenGL Engine",
            "outer_height_offset": 88,
            "chrome_major": major,
            "ua_data_platform": "macOS",
            "ua_data_platform_version": "13.0.0",
        }
    return {
        "languages": ["zh-CN", "zh", "en-US", "en"],
        "platform": "Linux x86_64",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "max_touch_points": 0,
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)",
        "outer_height_offset": 85,
        "chrome_major": major,
        "ua_data_platform": "Linux",
        "ua_data_platform_version": "",
    }


def stealth_init_script(settings: Settings) -> str:
    meta = stealth_fingerprint_meta(settings)
    return (
        f"window.__ANTIBOT_STEALTH_META__ = {json.dumps(meta, ensure_ascii=False)};\n"
        f"{_stealth_init_script_template()}"
    )


def profile_dir_for(
    settings: Settings,
    platform: str,
    tenant_id: str,
    account_id: str = "default",
) -> Path:
    from app.platforms.account_id import normalize_account_id
    from app.platforms.tenant import normalize_tenant_id

    safe = normalize_tenant_id(tenant_id)
    account = normalize_account_id(account_id)
    if platform == "douyin":
        base = settings.douyin_profile_dir
    else:
        base = settings.storage_root / platform / "profile"
    return base / safe / account


def persistent_profile_enabled(settings: Settings, platform: str) -> bool:
    del platform
    if not settings.antibot_persistent_profile:
        return False
    # 桌面端：登录态以 storage_state.json 为唯一真相源，不走 Chrome Profile（早期方案，避免双轨不同步）。
    if settings.desktop_mode:
        return False
    # Mac 系统 Chrome 不走 user-data-dir 持久化 Profile：Docker/Linux 遗留目录会损坏，
    # 且易与日常 Chrome 冲突（「打开个人资料出错」「正在现有的浏览器会话中打开」）。
    if py_platform.system() == "Darwin" and browser_channel(settings):
        return False
    return True


def headless_for_platform(settings: Settings, platform: str, headless: bool | None = None) -> bool:
    if headless is not None:
        return headless
    if platform == "xiaohongshu":
        return settings.xhs_headless
    if platform == "kuaishou":
        return settings.kuaishou_headless
    if platform == "douyin":
        return settings.douyin_headless
    return settings.agent_headless


def context_kwargs(settings: Settings, state: dict | None = None, *, headless: bool = True) -> dict:
    if uses_native_system_chrome(settings, headless=headless):
        # 系统 Chrome 由 _seed_storage_from_state 手工灌 Cookie；storage_state 参数易与 CDP 冲突。
        return {
            "locale": settings.antibot_locale,
            "timezone_id": settings.timezone,
            "no_viewport": True,
        }
    kwargs: dict = {
        "viewport": viewport(settings, headless=headless),
        "user_agent": user_agent(settings),
        "locale": settings.antibot_locale,
        "timezone_id": settings.timezone,
        "extra_http_headers": client_hints_headers(settings),
    }
    if state:
        kwargs["storage_state"] = state
    return kwargs


def persistent_context_kwargs(settings: Settings, *, headless: bool = True) -> dict:
    kwargs = context_kwargs(settings, None, headless=headless)
    kwargs.pop("storage_state", None)
    return kwargs


def visible_browser_launch_kwargs(settings: Settings | None = None) -> dict:
    import os

    resolved = settings or None
    if resolved is None:
        from app.core.config import get_settings

        resolved = get_settings()
    kwargs = launch_kwargs(resolved, headless=False)
    if os.environ.get("DISPLAY"):
        kwargs["env"] = os.environ.copy()
    return kwargs


async def launch_browser(playwright: Playwright, settings: Settings, *, headless: bool) -> Browser:
    from app.services.font_bootstrap import ensure_cjk_fonts_for_visible_browser

    await ensure_cjk_fonts_for_visible_browser(headless)
    kwargs = launch_kwargs(settings, headless=headless)
    return await playwright.chromium.launch(**kwargs)


# Playwright storage_state.origins 会收录 iframe/CDN 子域的 localStorage；
# 人工打开抖音时这些只在后台加载，不会在地址栏跳转。恢复时只灌主站 origin。
_SEEDABLE_LOCAL_STORAGE_HOSTS = frozenset(
    {
        "www.douyin.com",
        "douyin.com",
        "www.iesdouyin.com",
        "live.douyin.com",
        "www.xiaohongshu.com",
        "xiaohongshu.com",
        "www.kuaishou.com",
        "kuaishou.com",
    }
)


def _is_seedable_local_storage_origin(origin: str) -> bool:
    host = (urlparse(origin).hostname or "").lower().lstrip(".")
    if not host:
        return False
    if host in _SEEDABLE_LOCAL_STORAGE_HOSTS:
        return True
    # 字节 CDN / 静态资源域（lf-zt.douyin.com、*.yhgfb-cn-static.com 等）跳过。
    if host.startswith("lf-") or host.startswith("lf."):
        return False
    if "yhgfb" in host or "-static" in host or "byteimg" in host or "bytescm" in host:
        return False
    return False


def _warm_url_for_storage_state(state: dict | None) -> str | None:
    if not state:
        return None
    domains: set[str] = set()
    for cookie in state.get("cookies") or []:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if domain:
            domains.add(domain)
    for entry in state.get("origins") or []:
        if not isinstance(entry, dict):
            continue
        origin = str(entry.get("origin") or "").strip()
        if origin:
            domains.add(origin.removeprefix("https://").removeprefix("http://").split("/")[0].lower())
    for domain in sorted(domains):
        if domain.endswith("douyin.com"):
            return "https://www.douyin.com"
        if domain.endswith("xiaohongshu.com"):
            return "https://www.xiaohongshu.com"
    return None


def _cookie_url_for_playwright(domain: str, path: str) -> str | None:
    host = str(domain or "").strip().lstrip(".")
    if not host:
        return None
    normalized_path = str(path or "/") or "/"
    if host.endswith("douyin.com"):
        return f"https://www.douyin.com{normalized_path}"
    if host.endswith("xiaohongshu.com"):
        return f"https://www.xiaohongshu.com{normalized_path}"
    if host.endswith("kuaishou.com"):
        return f"https://www.kuaishou.com{normalized_path}"
    return f"https://{host}{normalized_path}"


def _normalize_storage_cookie_for_add(item: dict) -> dict | None:
    """Playwright add_cookies 只接受 url 或 domain 其一；storage_state 常两者并存。"""
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    if item.get("value") is None:
        return None

    cookie: dict = {"name": name, "value": str(item.get("value"))}
    raw_url = str(item.get("url") or "").strip()
    domain = str(item.get("domain") or "").strip()
    path = str(item.get("path") or "/")
    if raw_url:
        cookie["url"] = raw_url
    elif domain:
        resolved = _cookie_url_for_playwright(domain, path)
        if not resolved:
            return None
        cookie["url"] = resolved
    else:
        return None

    for key in ("expires", "httpOnly", "secure"):
        if key in item:
            cookie[key] = item[key]
    same_site = item.get("sameSite")
    if same_site in {"Lax", "Strict", "None"}:
        cookie["sameSite"] = same_site
    elif isinstance(same_site, str):
        lowered = same_site.lower()
        if lowered == "none":
            cookie["sameSite"] = "None"
        elif lowered == "strict":
            cookie["sameSite"] = "Strict"
        elif lowered == "lax":
            cookie["sameSite"] = "Lax"
    return cookie


async def _context_has_login_markers(context: BrowserContext, *, platform: str) -> bool:
    cookies = await context.cookies()
    names = {c.get("name") for c in cookies if isinstance(c, dict) and c.get("name")}
    if platform == "douyin":
        from app.platforms.douyin.session import USER_LOGIN_MARKERS

        return bool(names & USER_LOGIN_MARKERS)
    return bool(names)


async def ensure_platform_login_state(
    context: BrowserContext,
    page: Page,
    state: dict | None,
    settings: Settings,
    *,
    platform: str,
) -> Page:
    """系统 Chrome：灌 Cookie/localStorage 后校验登录态，登录墙则重灌并刷新。"""
    if not state or not uses_native_system_chrome(settings, headless=False):
        return page
    if platform != "douyin":
        return page

    from app.platforms.douyin.human_guards import _detect_login_wall

    if context.pages and context.pages[0] is not page and not page.is_closed():
        page = context.pages[0]

    if await _context_has_login_markers(context, platform=platform):
        if not await _detect_login_wall(page):
            return page

    if not await _context_has_login_markers(context, platform=platform):
        await _seed_storage_from_state(context, state, replace=True)
        with contextlib.suppress(Exception):
            await page.reload(wait_until="domcontentloaded", timeout=45000)

    if await _detect_login_wall(page):
        await _seed_storage_from_state(context, state, replace=True)
        with contextlib.suppress(Exception):
            await page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(800)

    return page


async def _seed_cookies_from_state(
    context: BrowserContext,
    state: dict | None,
    *,
    replace: bool = False,
) -> None:
    if not state:
        return
    raw_cookies = state.get("cookies") or []
    if not raw_cookies:
        return
    cookies: list[dict] = []
    for item in raw_cookies:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_storage_cookie_for_add(item)
        if normalized:
            cookies.append(normalized)
    if not cookies:
        return
    warm_url = _warm_url_for_storage_state(state)
    page = context.pages[0] if context.pages else await context.new_page()
    if warm_url:
        warm_host = (urlparse(warm_url).hostname or "").lower()
        current = (page.url or "").strip().lower()
        if warm_host and warm_host not in current:
            try:
                await page.goto(warm_url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
    try:
        if replace:
            await context.clear_cookies()
        await context.add_cookies(cookies)
    except Exception:
        added = 0
        for cookie in cookies:
            try:
                await context.add_cookies([cookie])
                added += 1
            except Exception:
                continue
        if added == 0 and not replace:
            with contextlib.suppress(Exception):
                await context.add_cookies(cookies)
    with contextlib.suppress(Exception):
        await page.reload(wait_until="domcontentloaded", timeout=45000)


async def _seed_local_storage_from_state(context: BrowserContext, state: dict | None) -> None:
    if not state:
        return
    origins = state.get("origins") or []
    if not origins:
        return
    page = context.pages[0] if context.pages else await context.new_page()
    for entry in origins:
        if not isinstance(entry, dict):
            continue
        origin = str(entry.get("origin") or "").strip()
        items = entry.get("localStorage") or []
        if not origin or not items or not _is_seedable_local_storage_origin(origin):
            continue
        try:
            await page.goto(origin, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(400)
            await page.evaluate(
                """(entries) => {
                    for (const item of entries) {
                        if (!item || item.name == null) continue;
                        localStorage.setItem(String(item.name), String(item.value ?? ''));
                    }
                }""",
                items,
            )
        except Exception:
            continue


async def _seed_storage_from_state(
    context: BrowserContext,
    state: dict | None,
    *,
    replace: bool = False,
) -> None:
    """把 storage_state.json 的 Cookie 与 localStorage 同步进浏览器上下文。"""
    await _seed_cookies_from_state(context, state, replace=replace)
    await _seed_local_storage_from_state(context, state)


async def _prepare_persistent_profile_launch(
    settings: Settings,
    platform: str,
    tenant_id: str,
    account_id: str,
    profile_dir: Path,
) -> None:
    from app.platforms.interactive_login import stop_interactive_session

    await stop_interactive_session(platform, tenant_id, account_id)
    terminate_chrome_for_profile(profile_dir)
    await asyncio.sleep(0.25)
    clear_stale_chrome_profile_locks(profile_dir)


async def launch_persistent_context(
    playwright: Playwright,
    settings: Settings,
    platform: str,
    tenant_id: str,
    store: PlatformSessionStore,
    *,
    headless: bool,
    account_id: str = "default",
) -> BrowserContext:
    from app.services.font_bootstrap import ensure_cjk_fonts_for_visible_browser

    await ensure_cjk_fonts_for_visible_browser(headless)
    profile_dir = profile_dir_for(settings, platform, tenant_id, account_id)
    profile_dir.mkdir(parents=True, exist_ok=True)
    seed_profile_protocol_prefs(profile_dir)
    state = store.load(tenant_id, account_id)
    kwargs = launch_kwargs(settings, headless=headless)
    kwargs.update(persistent_context_kwargs(settings, headless=headless))

    context: BrowserContext | None = None
    last_error: Exception | None = None
    for attempt in range(2):
        await _prepare_persistent_profile_launch(
            settings, platform, tenant_id, account_id, profile_dir
        )
        try:
            context = await playwright.chromium.launch_persistent_context(str(profile_dir), **kwargs)
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0 and "ProcessSingleton" in str(exc):
                continue
            raise
    if context is None:
        raise last_error from None  # type: ignore[misc]

    await apply_stealth(context, settings, tenant_id=tenant_id, visible=not headless)
    # Profile 仅有游客 Cookie 时，storage_state.json 仍可能是有效登录态，需补灌。
    if store.profile_needs_storage_seed(tenant_id, account_id) and state:
        await _seed_storage_from_state(context, state, replace=True)
    return context


async def new_browser_context(
    browser: Browser,
    settings: Settings,
    *,
    state: dict | None = None,
    tenant_id: str | None = None,
    visible: bool = False,
    **extra,
) -> BrowserContext:
    kwargs = context_kwargs(settings, state, headless=not visible)
    kwargs.update(extra)
    context = await browser.new_context(**kwargs)
    if uses_native_system_chrome(settings, headless=not visible):
        mark_native_system_chrome_context(context)
    await apply_stealth(context, settings, tenant_id=tenant_id, visible=visible)
    if state and uses_native_system_chrome(settings, headless=not visible):
        await _seed_storage_from_state(context, state, replace=False)
    return context


async def open_tenant_page(
    playwright: Playwright,
    settings: Settings,
    platform: str,
    tenant_id: str,
    store: PlatformSessionStore,
    *,
    headless: bool | None = None,
    account_id: str = "default",
    use_storage_state: bool = True,
) -> tuple[Browser | None, BrowserContext, Page]:
    resolved_headless = headless_for_platform(settings, platform, headless)
    state = store.load(tenant_id, account_id) if use_storage_state else None
    if persistent_profile_enabled(settings, platform):
        context = await launch_persistent_context(
            playwright,
            settings,
            platform,
            tenant_id,
            store,
            headless=resolved_headless,
            account_id=account_id,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        return None, context, page

    browser = await launch_browser(playwright, settings, headless=resolved_headless)
    context = await new_browser_context(
        browser,
        settings,
        state=state,
        tenant_id=tenant_id,
        visible=not resolved_headless,
    )
    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


@dataclass
class AntibotContext:
    settings: Settings
    tenant_id: str | None = None
    override: TenantAntibotOverrideOut | None = None

    @classmethod
    def for_tenant(cls, settings: Settings, tenant_id: str | None) -> AntibotContext:
        override = None
        if tenant_id:
            from app.services.tenant_antibot_store import TenantAntibotStore

            override = TenantAntibotStore(settings).load_safe(tenant_id)
        return cls(settings=settings, tenant_id=tenant_id, override=override)

    @property
    def enabled(self) -> bool:
        if self.override and self.override.enabled is not None:
            return self.override.enabled
        return self.settings.antibot_enabled

    @property
    def stealth_enabled(self) -> bool:
        if self.override and self.override.stealth_enabled is not None:
            return self.override.stealth_enabled
        return self.settings.antibot_stealth_enabled

    @property
    def require_login(self) -> bool:
        if self.override and self.override.require_login is not None:
            return self.override.require_login
        return self.settings.antibot_require_login

    @property
    def delay_min_ms(self) -> float:
        if self.override and self.override.delay_min_ms is not None:
            return float(self.override.delay_min_ms)
        return float(self.settings.antibot_delay_min_ms)

    @property
    def delay_max_ms(self) -> float:
        if self.override and self.override.delay_max_ms is not None:
            return float(self.override.delay_max_ms)
        return float(self.settings.antibot_delay_max_ms)

    @property
    def delay_multiplier(self) -> float:
        if self.override and self.override.delay_multiplier is not None:
            return float(self.override.delay_multiplier)
        return 1.0

    def delay_bounds(self, profile: str) -> tuple[float, float]:
        lo_mul, hi_mul = _DELAY_PROFILES.get(profile, _DELAY_PROFILES["default"])
        base_lo = self.delay_min_ms
        base_hi = self.delay_max_ms
        if base_hi < base_lo:
            base_lo, base_hi = base_hi, base_lo
        multiplier = self.delay_multiplier
        return base_lo * lo_mul * multiplier, base_hi * hi_mul * multiplier

    def delay_profiles(self) -> list[AntibotDelayProfileOut]:
        profiles: list[AntibotDelayProfileOut] = []
        for profile in _DELAY_PROFILES:
            lo, hi = self.delay_bounds(profile)
            profiles.append(AntibotDelayProfileOut(name=profile, min_ms=lo, max_ms=hi))
        return profiles

    def to_effective_config(self) -> AntibotGlobalConfigOut:
        return AntibotGlobalConfigOut(
            scope="effective",
            enabled=self.enabled,
            stealth_enabled=self.stealth_enabled,
            require_login=self.require_login,
            delay_min_ms=self.delay_min_ms,
            delay_max_ms=self.delay_max_ms,
            user_agent=user_agent(self.settings),
            viewport_width=self.settings.antibot_viewport_width,
            viewport_height=self.settings.antibot_viewport_height,
            locale=self.settings.antibot_locale,
            timezone=self.settings.timezone,
            stealth_version=STEALTH_VERSION,
            delay_profiles=self.delay_profiles(),
        )


def global_antibot_config(settings: Settings) -> AntibotGlobalConfigOut:
    return AntibotContext.for_tenant(settings, None).to_effective_config().model_copy(update={"scope": "global"})


def tenant_antibot_config(settings: Settings, tenant_id: str) -> TenantAntibotConfigOut:
    from app.services.tenant_antibot_store import TenantAntibotStore

    store = TenantAntibotStore(settings)
    override = store.load_safe(tenant_id)
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    path = store.path_for(tenant_id)
    return TenantAntibotConfigOut(
        tenant_id=tenant_id,
        override_path=str(path),
        has_override=override is not None and bool(override.model_dump(exclude_none=True)),
        override=override,
        effective=ctx.to_effective_config(),
    )


_TAB_GUARD_INSTALLED = "_huoke_tab_guard_installed"
_MAIN_PAGE_HOLDER = "_huoke_main_page_holder"
_WORK_TABS_ATTR = "_huoke_work_tab_ids"
_POPUP_SWEEPER_INSTALLED = "_huoke_popup_sweeper_installed"
_CDP_POPUP_KILLER_INSTALLED = "_huoke_cdp_popup_killer_installed"
_NATIVE_TAB_CLOSER_INSTALLED = "_huoke_native_tab_closer_installed"
_WINDOW_OPEN_GUARD_INSTALLED = "_huoke_window_open_guard_installed"
NATIVE_SYSTEM_CHROME_FLAG = "_huoke_native_system_chrome"

# 仅拦截埋点 window.open，不是 antibot 伪装；避免 tab 先画出再被 close 造成闪动。
_NATIVE_WINDOW_OPEN_GUARD_JS = """
(() => {
  if (window.__huokePopupGuard) return;
  window.__huokePopupGuard = true;
  const AUDIT = "__HUOKE_TAB_AUDIT__";
  const emit = (payload) => {
    try { console.info(AUDIT + JSON.stringify(payload)); } catch (e) {}
  };
  const nativeOpen = window.open;
  const isTrackingHost = (raw) => {
    const s = String(raw || '').trim();
    if (!s || s === 'about:blank') return true;
    try {
      const h = new URL(s, location.href).hostname.toLowerCase();
      if (h === 'www.douyin.com' || h === 'douyin.com') return false;
      if (h.startsWith('lf') && h.endsWith('.douyin.com')) return true;
      if (h.startsWith('lf-zt.') || h.startsWith('mon.') || h.startsWith('mcs.') || h.startsWith('log.')) return true;
      if (h.endsWith('.zijieapi.com')) return true;
    } catch (e) { return true; }
    return false;
  };
  const shouldBlock = (raw, target) => {
    if (isTrackingHost(raw)) return { block: true, reason: 'tracking_host' };
    const page = String(location.href || '');
    const onSearch = /\\/search\\//i.test(page);
    if (!onSearch) return { block: false, reason: '' };
    const t = String(target || '').toLowerCase();
    const isBlankTarget = t === '_blank' || t === 'blank' || t === 'new';
    try {
      const u = new URL(String(raw || ''), location.href);
      const path = (u.pathname || '').toLowerCase();
      if (path.includes('/user/')) return { block: true, reason: 'search_user_profile' };
      if (isBlankTarget && (u.hostname === 'www.douyin.com' || u.hostname === 'douyin.com')) {
        return { block: true, reason: 'search_douyin_blank_tab' };
      }
    } catch (e) { /* ignore */ }
    return { block: false, reason: '' };
  };
  window.open = function(url, target, features) {
    const decision = shouldBlock(url, target);
    const stack = (new Error('window.open')).stack || '';
    emit({
      event: 'window.open',
      action: decision.block ? 'blocked' : 'allowed',
      url: String(url || ''),
      target: String(target || ''),
      page_url: String(location.href || ''),
      tracking: decision.reason === 'tracking_host',
      blocked: decision.block,
      block_reason: decision.reason,
      stack: String(stack).slice(0, 800),
    });
    if (decision.block) return null;
    return nativeOpen.call(window, url, target, features);
  };
})();
"""


def mark_native_system_chrome_context(context: BrowserContext) -> None:
    setattr(context, NATIVE_SYSTEM_CHROME_FLAG, True)


def antibot_suppressed_for_page(page: Page | None) -> bool:
    """系统 Chrome 有头：靠 Skill 模拟人力，不走 antibot 延迟/伪装/注入。"""
    if page is None:
        return False
    try:
        return bool(getattr(page.context, NATIVE_SYSTEM_CHROME_FLAG, False))
    except Exception:
        return False


_CDP_CLOSED_TARGETS = "_huoke_cdp_closed_targets"
_MAIN_TARGET_ID_ATTR = "_huoke_main_target_id"
_BROWSER_REF_ATTR = "_huoke_browser_ref"


def _should_close_orphan_about_blank(
    *,
    url: str,
    has_opener: bool,
    target_id: str | None,
    main_target_id: str | None,
    main_page_url: str | None,
) -> bool:
    """无 opener 的 about:blank 仅在已锁定主 tab 且 target 非主 tab 时关闭。"""
    if has_opener:
        return False
    if (url or "").strip() != "about:blank":
        return False
    if not target_id or not main_target_id:
        return False
    if target_id == main_target_id:
        return False
    main_url = (main_page_url or "").strip()
    if not main_url or main_url == "about:blank":
        return False
    return True


async def _resolve_main_target_id(browser: Browser, main_page: Page) -> str | None:
    """主 tab 已导航到真实 URL 后，用 CDP 锁定 targetId，避免误关主 tab。"""
    try:
        cdp = await browser.new_browser_cdp_session()
        targets = await cdp.send("Target.getTargets")
        main_url = (main_page.url or "").strip()
        if not main_url or main_url == "about:blank":
            return None
        best: str | None = None
        for info in targets.get("targetInfos", []):
            if info.get("type") != "page":
                continue
            tid = info.get("targetId")
            if not tid:
                continue
            if (info.get("url") or "").strip() != main_url:
                continue
            best = tid
            if info.get("attached"):
                return tid
        return best
    except Exception:
        return None


async def _maybe_refresh_main_target_id(context: BrowserContext) -> str | None:
    cached = getattr(context, _MAIN_TARGET_ID_ATTR, None)
    holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {}
    main = holder.get("page")
    if main is None or main.is_closed():
        return cached
    main_url = (main.url or "").strip()
    if not main_url or main_url == "about:blank":
        return None
    if cached:
        return cached
    browser: Browser | None = getattr(context, _BROWSER_REF_ATTR, None)
    if browser is None:
        with contextlib.suppress(Exception):
            browser = context.browser
    if browser is None:
        return None
    tid = await _resolve_main_target_id(browser, main)
    if tid:
        setattr(context, _MAIN_TARGET_ID_ATTR, tid)
    return tid


def _is_tracking_popup_url(url: str) -> bool:
    """仅明确埋点域 / about:blank 视为可关 popup；空 URL 是 tab 尚未导航，勿关。"""
    raw = (url or "").strip()
    if not raw:
        return False
    if raw == "about:blank":
        return True
    host = (urlparse(raw).hostname or "").lower()
    if not host:
        return False
    if host in {"www.douyin.com", "douyin.com"}:
        return False
    if host.startswith("lf") and host.endswith(".douyin.com"):
        return True
    if host.startswith(("lf-zt.", "mon.", "mcs.", "log.")):
        return True
    if host.endswith(".zijieapi.com"):
        return True
    return False


def _mark_cdp_closed_target(context: BrowserContext, target_id: str) -> None:
    closed: set[str] = getattr(context, _CDP_CLOSED_TARGETS, None) or set()
    closed.add(target_id)
    setattr(context, _CDP_CLOSED_TARGETS, closed)


def _should_kill_popup_page(page: Page, main: Page | None) -> bool:
    return page is not main and not page.is_closed()


async def _kill_popup_page(page: Page, main: Page | None) -> None:
    if not _should_kill_popup_page(page, main):
        return
    if _is_work_tab(page.context, page):
        return
    with contextlib.suppress(Exception):
        await page.close(run_before_unload=False)


async def _page_looks_like_tracking_popup(page: Page) -> bool:
    """判断是否埋点 popup tab（about:blank 立即判定，不再等待渲染）。"""
    return _is_tracking_popup_url((page.url or "").strip())


async def _install_window_open_guard(
    context: BrowserContext,
    main_page: Page | None = None,
) -> None:
    """主 tab 注入：从源头 noop 埋点 window.open，避免 Chrome 画出 popup tab。"""
    if getattr(context, _WINDOW_OPEN_GUARD_INSTALLED, False):
        return
    with contextlib.suppress(Exception):
        await context.add_init_script(_NATIVE_WINDOW_OPEN_GUARD_JS)
    if main_page is not None:
        with contextlib.suppress(Exception):
            await main_page.evaluate(_NATIVE_WINDOW_OPEN_GUARD_JS)
    setattr(context, _WINDOW_OPEN_GUARD_INSTALLED, True)


def _ensure_native_tracking_tab_closer(context: BrowserContext) -> None:
    """系统 Chrome 兜底：仅关埋点 popup tab，不 bring_to_front、不注入脚本。"""
    if getattr(context, _NATIVE_TAB_CLOSER_INSTALLED, False):
        return

    async def _close_tracking_popup(page: Page) -> None:
        from app.services.popup_tab_audit import record_tab_audit

        # CDP 已关的 popup 会晚到 page 事件；略等再判，避免双关闪屏。
        await asyncio.sleep(0.12)
        holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {}
        main = holder.get("page")
        if page is main:
            record_tab_audit(
                context,
                "tab_close_skipped",
                source="native_tracking_closer",
                url=(page.url or ""),
                reason="is_main_tab",
            )
            return
        if _is_work_tab(context, page):
            record_tab_audit(
                context,
                "tab_close_skipped",
                source="native_tracking_closer",
                url=(page.url or ""),
                reason="work_tab",
            )
            return
        if page.is_closed():
            record_tab_audit(
                context,
                "tab_close_skipped",
                source="native_tracking_closer",
                reason="already_closed_by_cdp",
            )
            return
        popup_url = (page.url or "").strip()
        if not await _page_looks_like_tracking_popup(page):
            record_tab_audit(
                context,
                "tab_close_skipped",
                source="native_tracking_closer",
                url=popup_url,
                reason="not_tracking_url",
            )
            return
        record_tab_audit(
            context,
            "tab_close",
            source="native_tracking_closer",
            action="page.close",
            url=popup_url,
            reason="tracking_popup_fallback",
        )
        with contextlib.suppress(Exception):
            await page.close(run_before_unload=False)

    def _on_page(page: Page) -> None:
        try:
            asyncio.get_running_loop().create_task(_close_tracking_popup(page))
        except RuntimeError:
            pass

    context.on("page", _on_page)
    setattr(context, _NATIVE_TAB_CLOSER_INSTALLED, True)


def _ensure_popup_tab_sweeper(context: BrowserContext) -> None:
    """非系统 Chrome 模式：关掉非主 tab（不抢焦点）。"""
    if getattr(context, _POPUP_SWEEPER_INSTALLED, False):
        return

    async def _sweep_popup(page: Page) -> None:
        holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {}
        main = holder.get("page")
        if page is main or page.is_closed():
            return
        await _kill_popup_page(page, main)

    def _on_page(page: Page) -> None:
        holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {}
        main = holder.get("page")
        if page is main:
            return
        try:
            asyncio.get_running_loop().create_task(_sweep_popup(page))
        except RuntimeError:
            pass

    context.on("page", _on_page)
    setattr(context, _POPUP_SWEEPER_INSTALLED, True)


async def _install_cdp_popup_killer(browser: Browser, context: BrowserContext) -> None:
    """CDP 层：在 about:blank/lf-zt 渲染前就关闭新 target，避免白屏抢焦点。"""
    if getattr(context, _CDP_POPUP_KILLER_INSTALLED, False):
        return
    try:
        cdp = await browser.new_browser_cdp_session()
    except Exception:
        return

    setattr(context, _CDP_POPUP_KILLER_INSTALLED, True)
    setattr(context, _BROWSER_REF_ATTR, browser)

    async def _on_target_created(params: dict) -> None:
        from app.services.popup_tab_audit import record_tab_audit

        info = params.get("targetInfo") or {}
        if info.get("type") != "page":
            return
        target_id = info.get("targetId")
        url = (info.get("url") or "").strip()
        has_opener = bool(info.get("openerFrameId") or info.get("openerId"))
        tracking = _is_tracking_popup_url(url)
        holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {}
        main = holder.get("page")
        main_url = (main.url or "").strip() if main is not None and not main.is_closed() else ""
        main_target_id = await _maybe_refresh_main_target_id(context)
        close_orphan = _should_close_orphan_about_blank(
            url=url,
            has_opener=has_opener,
            target_id=target_id,
            main_target_id=main_target_id,
            main_page_url=main_url,
        )
        will_close = bool(target_id and ((has_opener and tracking) or close_orphan))
        record_tab_audit(
            context,
            "cdp_target_created",
            source="cdp.Target.targetCreated",
            url=url,
            target_id=target_id,
            opener_id=info.get("openerId"),
            opener_frame_id=info.get("openerFrameId"),
            has_opener=has_opener,
            tracking=tracking,
            will_close=will_close,
            main_target_id=main_target_id,
            close_orphan=close_orphan,
        )
        if not target_id:
            return
        if has_opener:
            if not tracking:
                return
            close_reason = "tracking_popup_cdp"
        elif close_orphan:
            close_reason = "orphan_about_blank_cdp"
        else:
            return
        _mark_cdp_closed_target(context, target_id)
        record_tab_audit(
            context,
            "tab_close",
            source="cdp_popup_killer",
            action="Target.closeTarget",
            url=url,
            target_id=target_id,
            reason=close_reason,
        )
        with contextlib.suppress(Exception):
            await cdp.send("Target.closeTarget", {"targetId": target_id})

    def _handler(params: dict) -> None:
        try:
            asyncio.get_running_loop().create_task(_on_target_created(params))
        except RuntimeError:
            pass

    cdp.on("Target.targetCreated", _handler)
    with contextlib.suppress(Exception):
        await cdp.send("Target.setDiscoverTargets", {"discover": True})


async def bind_main_page_guards(
    context: BrowserContext,
    main_page: Page,
    *,
    browser: Browser | None = None,
    settings: Settings | None = None,
    headless: bool = True,
    install_cdp: bool = True,
) -> None:
    """登记主 tab，并安装 popup 守卫（系统 Chrome：CDP 预关 + 仅埋点 URL 兜底）。"""
    holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {"page": None}
    holder["page"] = main_page
    setattr(context, _MAIN_PAGE_HOLDER, holder)
    setattr(context, _TAB_GUARD_INSTALLED, True)

    is_native = getattr(context, NATIVE_SYSTEM_CHROME_FLAG, False) or (
        settings is not None and uses_native_system_chrome(settings, headless=headless)
    )
    if is_native:
        await _install_window_open_guard(context, main_page)
        _ensure_native_tracking_tab_closer(context)
    else:
        _ensure_popup_tab_sweeper(context)

    resolved_browser = browser
    if resolved_browser is None:
        with contextlib.suppress(Exception):
            resolved_browser = context.browser
    if resolved_browser is not None and install_cdp:
        with contextlib.suppress(asyncio.TimeoutError, Exception):
            await asyncio.wait_for(
                _install_cdp_popup_killer(resolved_browser, context),
                timeout=5.0,
            )
        setattr(context, _BROWSER_REF_ATTR, resolved_browser)

    from app.services.popup_tab_audit import install_tab_audit_bridge

    await install_tab_audit_bridge(context, main_page)


async def bind_main_browser_tab(
    context: BrowserContext,
    main_page: Page,
    *,
    browser: Browser | None = None,
    settings: Settings | None = None,
    headless: bool = True,
) -> None:
    """登记主 tab 并启用 popup 拦截。"""
    await bind_main_page_guards(
        context,
        main_page,
        browser=browser,
        settings=settings,
        headless=headless,
    )


def register_work_tab(context: BrowserContext, page: Page) -> None:
    """登记业务 Tab（测试/多步骤），避免 native tab closer 误关 about:blank 新页。"""
    tabs: set[int] = getattr(context, _WORK_TABS_ATTR, None) or set()
    tabs.add(id(page))
    setattr(context, _WORK_TABS_ATTR, tabs)


def unregister_work_tab(context: BrowserContext, page: Page) -> None:
    tabs: set[int] = getattr(context, _WORK_TABS_ATTR, None) or set()
    tabs.discard(id(page))
    setattr(context, _WORK_TABS_ATTR, tabs)


def _is_work_tab(context: BrowserContext, page: Page) -> bool:
    tabs: set[int] = getattr(context, _WORK_TABS_ATTR, None) or set()
    return id(page) in tabs


def register_main_page(context: BrowserContext, main_page: Page) -> None:
    """同步登记主 tab（复用已有 context 时；完整守卫见 bind_main_page_guards）。"""
    holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {"page": None}
    holder["page"] = main_page
    setattr(context, _MAIN_PAGE_HOLDER, holder)
    setattr(context, _TAB_GUARD_INSTALLED, True)
    if getattr(context, NATIVE_SYSTEM_CHROME_FLAG, False):
        _ensure_native_tracking_tab_closer(context)
    else:
        _ensure_popup_tab_sweeper(context)


async def install_single_tab_guard(
    context: BrowserContext,
    main_page: Page,
    *,
    browser: Browser | None = None,
    settings: Settings | None = None,
    headless: bool = True,
) -> None:
    await bind_main_browser_tab(
        context,
        main_page,
        browser=browser,
        settings=settings,
        headless=headless,
    )


async def apply_stealth(
    context: BrowserContext,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    visible: bool = False,
) -> None:
    if uses_native_system_chrome(settings, headless=not visible):
        return
    await install_external_protocol_guard(context)
    await install_dialog_auto_dismiss(context)
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if ctx.stealth_enabled:
        await context.add_init_script(stealth_init_script(settings))


async def human_delay(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    profile: str = "default",
) -> None:
    if antibot_suppressed_for_page(page):
        return
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.enabled:
        return
    lo, hi = ctx.delay_bounds(profile)
    await page.wait_for_timeout(random.uniform(lo, hi))


async def human_pause(
    settings: Settings,
    *,
    tenant_id: str | None = None,
    profile: str = "default",
    page: Page | None = None,
) -> None:
    if antibot_suppressed_for_page(page):
        return
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.enabled:
        return
    lo, hi = ctx.delay_bounds(profile)
    await asyncio.sleep(random.uniform(lo, hi) / 1000.0)


def _bezier_points(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    steps: int,
) -> list[tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    distance = math.hypot(ex - sx, ey - sy)
    spread = max(40.0, distance * 0.35)
    c1 = (sx + random.uniform(-spread, spread), sy + random.uniform(-spread, spread))
    c2 = (ex + random.uniform(-spread, spread), ey + random.uniform(-spread, spread))
    points: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = (
            u * u * u * sx
            + 3 * u * u * t * c1[0]
            + 3 * u * t * t * c2[0]
            + t * t * t * ex
        )
        y = (
            u * u * u * sy
            + 3 * u * u * t * c1[1]
            + 3 * u * t * t * c2[1]
            + t * t * t * ey
        )
        points.append((x, y))
    return points


def _default_mouse_origin(page: Page) -> tuple[float, float]:
    vp = page.viewport_size or {"width": 1440, "height": 1200}
    return (
        random.uniform(vp["width"] * 0.25, vp["width"] * 0.75),
        random.uniform(vp["height"] * 0.15, vp["height"] * 0.55),
    )


async def human_mouse_move(
    page: Page,
    x: float,
    y: float,
    settings: Settings,
    *,
    tenant_id: str | None = None,
) -> None:
    if antibot_suppressed_for_page(page):
        await page.mouse.move(x, y)
        return
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.enabled:
        await page.mouse.move(x, y)
        return
    page_id = id(page)
    start = _last_mouse_pos.get(page_id, _default_mouse_origin(page))
    steps = random.randint(14, 32)
    for px, py in _bezier_points(start, (x, y), steps=steps):
        await page.mouse.move(px, py)
        await asyncio.sleep(random.uniform(0.004, 0.022))
    _last_mouse_pos[page_id] = (x, y)


async def _neutralize_hidden_pointer_blockers(page: Page) -> None:
    """抖音常留隐藏 #captcha_container，Playwright 会认为拦截点击但人眼不可见。"""
    with contextlib.suppress(Exception):
        await page.evaluate(
            """() => {
              const ids = ['captcha_container', 'captcha-verify-image'];
              for (const id of ids) {
                const el = document.getElementById(id);
                if (!el) continue;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const visible = style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && parseFloat(style.opacity || '1') > 0.05
                  && rect.width > 8
                  && rect.height > 8;
                if (!visible) {
                  el.style.pointerEvents = 'none';
                  el.style.display = 'none';
                }
              }
            }"""
        )


async def human_click(
    page: Page,
    target: str | Locator,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    timeout: float = 10000,
) -> None:
    locator = page.locator(target).first if isinstance(target, str) else target
    await locator.wait_for(state="visible", timeout=timeout)
    if antibot_suppressed_for_page(page):
        await _neutralize_hidden_pointer_blockers(page)
        box = await locator.bounding_box()
        if box:
            x = box["x"] + box["width"] * random.uniform(0.28, 0.72)
            y = box["y"] + box["height"] * random.uniform(0.28, 0.72)
            await page.mouse.click(x, y)
            return
        await locator.click(timeout=timeout, force=True)
        return
    box = await locator.bounding_box()
    if not box:
        await locator.click(timeout=timeout)
        return
    x = box["x"] + box["width"] * random.uniform(0.28, 0.72)
    y = box["y"] + box["height"] * random.uniform(0.28, 0.72)
    await human_mouse_move(page, x, y, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="action")
    await page.mouse.click(x, y)


async def human_type(
    page: Page,
    target: str | Locator,
    text: str,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    timeout: float = 10000,
    clear_first: bool = True,
) -> None:
    locator = page.locator(target).first if isinstance(target, str) else target
    if antibot_suppressed_for_page(page):
        await locator.wait_for(state="visible", timeout=timeout)
        await _neutralize_hidden_pointer_blockers(page)
        box = await locator.bounding_box()
        if box:
            x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
            y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
            await page.mouse.click(x, y)
        else:
            await locator.click(timeout=timeout, force=True)
        if clear_first:
            modifier = "Meta" if py_platform.system() == "Darwin" else "Control"
            await page.keyboard.press(f"{modifier}+A")
            await asyncio.sleep(0.05)
            await page.keyboard.press("Backspace")
        await page.keyboard.type(text, delay=random.randint(25, 80))
        return
    await human_click(page, locator, settings, tenant_id=tenant_id, timeout=timeout)
    if clear_first:
        modifier = "Meta" if py_platform.system() == "Darwin" else "Control"
        await page.keyboard.press(f"{modifier}+A")
        await asyncio.sleep(random.uniform(0.04, 0.12))
        await page.keyboard.press("Backspace")
        await asyncio.sleep(random.uniform(0.05, 0.15))
    for char in text:
        await page.keyboard.type(char, delay=random.randint(35, 190))
        if random.random() < 0.06:
            await human_pause(settings, tenant_id=tenant_id, profile="action", page=page)


async def human_scroll(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str | None = None,
    delta_y: int | None = None,
    profile: str = "scroll",
) -> None:
    if delta_y is None:
        delta_y = random.randint(700, 2200)
    if antibot_suppressed_for_page(page):
        await page.mouse.wheel(0, delta_y)
        return
    direction = 1 if delta_y >= 0 else -1
    total = abs(delta_y)
    segments = random.randint(2, 5)
    remaining = total
    for index in range(segments):
        if index == segments - 1:
            chunk = remaining
        else:
            chunk = max(60, int(remaining * random.uniform(0.18, 0.45)))
            remaining -= chunk
        sub_steps = random.randint(2, 5)
        step_size = max(20, chunk // sub_steps)
        for _ in range(sub_steps):
            jitter = random.randint(-18, 18)
            await page.mouse.wheel(0, direction * (step_size + jitter))
            await asyncio.sleep(random.uniform(0.02, 0.09))
        await human_delay(page, settings, tenant_id=tenant_id, profile=profile)
    if direction > 0 and random.random() < 0.28:
        await page.mouse.wheel(0, -random.randint(60, 260))
        await human_delay(page, settings, tenant_id=tenant_id, profile=profile)


async def warmup_douyin(
    page: Page,
    settings: Settings,
    *,
    tenant_id: str | None = None,
) -> None:
    current = (page.url or "").strip().lower()
    needs_entry = not current or current == "about:blank" or current.startswith("about:blank")
    if antibot_suppressed_for_page(page) and not needs_entry:
        return
    if not settings.antibot_warmup_enabled and not needs_entry:
        return
    home_url = settings.douyin_home_url
    try:
        if needs_entry or "douyin.com" not in current:
            await page.goto(home_url, wait_until="domcontentloaded", timeout=120000)
    except Exception:
        return
    if antibot_suppressed_for_page(page):
        return
    await human_delay(page, settings, tenant_id=tenant_id, profile="warmup")
    await human_scroll(page, settings, tenant_id=tenant_id)
    await human_delay(page, settings, tenant_id=tenant_id, profile="warmup")


def require_login(
    store: PlatformSessionStore,
    tenant_id: str,
    settings: Settings,
    account_id: str = "default",
) -> None:
    ctx = AntibotContext.for_tenant(settings, tenant_id)
    if not ctx.require_login:
        return
    if hasattr(store, "is_usable") and callable(getattr(store, "is_usable")):
        if store.is_usable(tenant_id, account_id):
            return
    state = store.load(tenant_id, account_id)
    if store.is_ready(state):
        return
    status = store.login_status(tenant_id, account_id)
    if settings.desktop_mode and status.get("profile_ready"):
        return
    raise LoginRequiredError(
        status.get("message")
        or f"{store.platform} 账号 {account_id} 缺少有效登录态，请先完成绑定。"
    )
