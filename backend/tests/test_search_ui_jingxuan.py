from __future__ import annotations

from app.services.ui_flow.platforms.douyin.search_ui import (
    _jingxuan_search_url,
    _on_search_results_page,
    _www_search_url,
)


def test_jingxuan_search_url_encoding():
    url = _jingxuan_search_url("团餐配送")
    assert "/jingxuan/search/" in url
    assert "type=general" in url
    assert _on_search_results_page(url)


def test_on_search_results_page():
    assert _on_search_results_page("https://www.douyin.com/jingxuan/search/foo?type=general")
    assert not _on_search_results_page("https://www.douyin.com/jingxuan")


def test_www_search_url():
    assert "/search/" in _www_search_url("test")
    assert "type=general" in _www_search_url("test")


def test_is_general_search_page():
    from app.services.ui_flow.platforms.douyin.search_ui import _is_general_search_page

    assert _is_general_search_page("https://www.douyin.com/search/foo?type=general")
    assert _is_general_search_page("https://www.douyin.com/jingxuan/search/foo?type=general")
    assert not _is_general_search_page("https://www.douyin.com/search/foo?type=video")
    assert not _is_general_search_page("https://www.douyin.com/jingxuan")
