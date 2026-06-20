from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.core.antibot import (
    _is_tracking_popup_url,
    _normalize_storage_cookie_for_add,
    _should_close_orphan_about_blank,
    apply_stealth,
    antibot_suppressed_for_page,
    bind_main_page_guards,
    context_kwargs,
    human_delay,
    launch_args,
    mark_native_system_chrome_context,
    uses_native_system_chrome,
)
from app.core.config import Settings


def test_normalize_storage_cookie_for_add_strips_domain_when_url_set():
    normalized = _normalize_storage_cookie_for_add(
        {
            "name": "sessionid",
            "value": "abc",
            "domain": ".douyin.com",
            "path": "/",
            "sameSite": "Lax",
            "httpOnly": True,
            "secure": True,
        }
    )
    assert normalized is not None
    assert normalized["url"] == "https://www.douyin.com/"
    assert "domain" not in normalized
    assert normalized["sameSite"] == "Lax"


def test_normalize_storage_cookie_for_add_skips_empty_name():
    assert _normalize_storage_cookie_for_add({"name": "", "domain": ".douyin.com"}) is None


def test_uses_native_system_chrome_when_channel_and_visible():
    settings = Settings(antibot_browser_channel="chrome")
    assert uses_native_system_chrome(settings, headless=False) is True
    assert uses_native_system_chrome(settings, headless=True) is False


def test_uses_native_system_chrome_false_without_channel():
    settings = Settings(antibot_browser_channel="")
    assert uses_native_system_chrome(settings, headless=False) is False


def test_launch_args_empty_for_native_system_chrome():
    settings = Settings(antibot_browser_channel="chrome")
    assert launch_args(settings, headless=False) == []


def test_launch_args_desktop_native_chrome_suppresses_profile_promo():
    settings = Settings(antibot_browser_channel="chrome", desktop_mode=True)
    args = launch_args(settings, headless=False)
    assert "--disable-signin-promo" in args
    assert any("SignInProfileCreation" in arg for arg in args)


def test_launch_kwargs_ignore_automation_flag_for_native():
    from app.core.antibot import launch_kwargs

    settings = Settings(antibot_browser_channel="chrome")
    kwargs = launch_kwargs(settings, headless=False)
    assert kwargs.get("channel") == "chrome"
    ignored = kwargs.get("ignore_default_args") or []
    assert "--enable-automation" in ignored
    import platform as py_platform

    if py_platform.system() == "Darwin":
        assert "--no-startup-window" in ignored


def test_launch_args_keep_antibot_for_headless_channel():
    settings = Settings(antibot_browser_channel="chrome")
    args = launch_args(settings, headless=True)
    assert "--disable-blink-features=AutomationControlled" in args


def test_context_kwargs_minimal_for_native_system_chrome():
    settings = Settings(antibot_browser_channel="chrome")
    kwargs = context_kwargs(settings, {"cookies": []}, headless=False)
    assert kwargs.get("no_viewport") is True
    assert "user_agent" not in kwargs
    assert "extra_http_headers" not in kwargs
    assert kwargs.get("locale") == settings.antibot_locale


def test_apply_stealth_skips_native_system_chrome():
    settings = Settings(antibot_browser_channel="chrome")
    context = AsyncMock()
    with patch("app.core.antibot.install_external_protocol_guard", AsyncMock()) as guard:
        asyncio.run(apply_stealth(context, settings, visible=True))
    guard.assert_not_called()
    context.add_init_script.assert_not_called()


async def _human_delay_probe(page):
    await human_delay(page, Settings(antibot_enabled=True), profile="default")


def test_human_delay_skips_on_native_system_chrome_context():
    page = AsyncMock()
    page.context = AsyncMock()
    mark_native_system_chrome_context(page.context)
    assert antibot_suppressed_for_page(page) is True
    asyncio.run(_human_delay_probe(page))
    page.wait_for_timeout.assert_not_called()


def test_tracking_popup_url_detection():
    assert _is_tracking_popup_url("") is False
    assert _is_tracking_popup_url("about:blank") is True
    assert _is_tracking_popup_url("https://lf-zt.douyin.com/foo") is True
    assert _is_tracking_popup_url("https://www.douyin.com/jingxuan") is False
    assert _is_tracking_popup_url("https://www.douyin.com/user/MS4wLjABAAAA") is False


def test_should_close_orphan_about_blank_only_non_main():
    assert _should_close_orphan_about_blank(
        url="about:blank",
        has_opener=False,
        target_id="B",
        main_target_id="A",
        main_page_url="https://www.douyin.com/jingxuan",
    ) is True
    assert _should_close_orphan_about_blank(
        url="about:blank",
        has_opener=False,
        target_id="A",
        main_target_id="A",
        main_page_url="https://www.douyin.com/jingxuan",
    ) is False
    assert _should_close_orphan_about_blank(
        url="about:blank",
        has_opener=False,
        target_id="B",
        main_target_id=None,
        main_page_url="https://www.douyin.com/jingxuan",
    ) is False
    assert _should_close_orphan_about_blank(
        url="about:blank",
        has_opener=True,
        target_id="B",
        main_target_id="A",
        main_page_url="https://www.douyin.com/jingxuan",
    ) is False
    assert _should_close_orphan_about_blank(
        url="about:blank",
        has_opener=False,
        target_id="B",
        main_target_id="A",
        main_page_url="about:blank",
    ) is False


async def _bind_native_guards_probe():
    from types import SimpleNamespace

    context = SimpleNamespace(browser=AsyncMock(), on=lambda *_a, **_k: None)
    mark_native_system_chrome_context(context)
    main = AsyncMock()
    main.evaluate = AsyncMock()
    with patch("app.core.antibot._install_cdp_popup_killer", AsyncMock()) as cdp:
        with patch("app.core.antibot._install_window_open_guard", AsyncMock()) as guard:
            await bind_main_page_guards(context, main, settings=Settings(antibot_browser_channel="chrome"))
    cdp.assert_awaited_once()
    guard.assert_awaited_once()
    assert getattr(context, "_huoke_native_tab_closer_installed", False) is True


def test_bind_main_page_guards_installs_cdp_for_native_chrome():
    asyncio.run(_bind_native_guards_probe())
