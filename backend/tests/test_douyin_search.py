from __future__ import annotations

import inspect

from app.core.config import Settings
from app.platforms.douyin.search import DouyinSearchTool, _JS_REMOVED_HINT
from app.platforms.douyin.session import DouyinSessionStore


def test_record_search_nil_accepts_empty_hints_dict():
    hints: dict[str, str] = {}
    data = {
        "search_nil_info": {
            "search_nil_type": "verify_check",
            "search_nil_item": "verify_check",
        }
    }
    DouyinSearchTool._record_search_nil(data, hints)
    assert hints.get("nil_type") == "verify_check"
    assert "verify_check" in (hints.get("diagnostic") or "")


def test_search_nil_verify_check_diagnostic():
    data = {
        "status_code": 0,
        "data": [],
        "search_nil_info": {
            "search_nil_type": "verify_check",
            "search_nil_item": "verify_check",
            "text_type": 9,
        },
    }
    msg = DouyinSearchTool._search_nil_diagnostic(data)
    assert msg is not None
    assert "verify_check" in msg
    assert "show_browser" in msg


def test_keyword_search_is_instance_method():
    sig = inspect.signature(DouyinSearchTool.keyword_search)
    params = list(sig.parameters.keys())
    assert params == [
        "self",
        "page",
        "keyword",
        "limit",
        "captured_api_urls",
        "region",
        "days",
        "headless",
        "manual_search",
        "search_url_first",
        "ui_search_only",
        "watched_skip",
    ]
    raw = DouyinSearchTool.__dict__["keyword_search"]
    assert not isinstance(raw, staticmethod)

    tool = DouyinSearchTool(Settings(), "default", DouyinSessionStore(Settings()))
    bound = tool.keyword_search
    assert getattr(bound, "__self__", None) is tool


def test_removed_legacy_search_paths():
    removed = (
        "_thin_browser_keyword_search",
        "_search_videos_via_thin_nav",
        "search_videos_from_existing_page",
        "_collect_keyword_search_results",
        "_search_videos_via_js_api",
        "_trigger_keyword_search",
        "_direct_search_urls",
        "_goto_search_results_direct",
        "warmup_for_js_api",
        "pick_api_template_url",
        "fetch_json_via_page",
    )
    for name in removed:
        assert not hasattr(DouyinSearchTool, name), f"{name} should be removed"

    assert hasattr(DouyinSearchTool, "keyword_search")
    assert _JS_REMOVED_HINT
