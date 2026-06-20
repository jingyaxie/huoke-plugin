from __future__ import annotations

from app.core.antibot import (
    _EXTERNAL_PROTOCOL_GUARD_JS,
    _is_tracking_popup_url,
)


def test_external_protocol_guard_redirects_blank_links():
    assert "target === '_blank'" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "safeSameTabNav(href)" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "ev.metaKey" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "auxclick" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "isTrackingUrl" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "isPopupOnlyUrl" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "about:blank" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "normalizeFormTarget" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert r"lf[\w-]*\.douyin\.com" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "origOpen.call(window" not in _EXTERNAL_PROTOCOL_GUARD_JS


def test_external_protocol_guard_still_blocks_custom_schemes():
    assert "blockNav(url)" in _EXTERNAL_PROTOCOL_GUARD_JS
    assert "return null" in _EXTERNAL_PROTOCOL_GUARD_JS


def test_tracking_popup_url_detection():
    assert _is_tracking_popup_url("about:blank")
    assert _is_tracking_popup_url("https://lf-zt.douyin.com/")
    assert _is_tracking_popup_url("https://lf3-cdn-tos.douyin.com/foo")
    assert not _is_tracking_popup_url("https://www.douyin.com/jingxuan")
    assert not _is_tracking_popup_url(
        "https://www.douyin.com/jingxuan/search/%E5%9B%A2%E9%A4%90%E9%85%8D%E9%80%81"
    )
