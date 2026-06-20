from __future__ import annotations

from app.services.ui_flow.params import parse_ui_flow_params
from app.services.ui_flow.platforms.douyin.search_parse import (
    analyze_search_api_response,
    extract_aweme_items_from_json,
    is_search_result_api,
    search_api_min_items,
    search_nil_type,
)
from app.services.platform_skill_map import crawl_skill_for_platform, platform_for_skill_id


def test_parse_ui_flow_params_defaults():
    params = parse_ui_flow_params({"keyword": "团餐配送"}, platform="douyin")
    assert params.platform == "douyin"
    assert params.keyword == "团餐配送"
    assert params.content_limit == 5
    assert params.show_browser is True
    assert params.skip_search_filter is False
    assert params.entry == "home"


def test_parse_ui_flow_params_platform_options():
    params = parse_ui_flow_params(
        {"keyword": "test", "platform_options": {"entry": "home"}, "content_limit": 1},
        platform="douyin",
    )
    assert params.entry == "home"
    assert params.content_limit == 1


def test_search_parse_verify_check():
    data = {"search_nil_info": {"search_nil_type": "verify_check"}}
    assert search_nil_type(data) == "verify_check"
    outcome = analyze_search_api_response(data)
    assert outcome.verify_check is True
    assert outcome.ready is False


def test_search_api_min_items_caps_at_three():
    assert search_api_min_items(50) == 3
    assert search_api_min_items(1) == 1


def test_analyze_search_api_response_items_ready():
    data = {
        "status_code": 0,
        "data": [
            {
                "aweme_info": {
                    "aweme_id": "7123456789012345678",
                    "desc": "AI获客",
                    "author": {"uid": "1", "nickname": "作者"},
                    "statistics": {"digg_count": 10},
                }
            }
        ],
        "has_more": 1,
    }
    outcome = analyze_search_api_response(data, min_items=1)
    assert outcome.ready is True
    assert outcome.item_count == 1
    assert outcome.reason.startswith("items=")


def test_analyze_search_api_response_explicit_empty():
    data = {"search_nil_info": {"search_nil_type": "empty"}, "status_code": 0, "data": [], "has_more": 0}
    outcome = analyze_search_api_response(data)
    assert outcome.ready is True
    assert outcome.explicit_empty is True
    assert outcome.reason == "nil=empty"


def test_analyze_search_api_response_has_more_zero():
    data = {"status_code": 0, "data": [], "has_more": 0}
    outcome = analyze_search_api_response(data)
    assert outcome.ready is True
    assert outcome.reason == "has_more=0"


def test_search_parse_extract_aweme():
    data = {
        "data": [
            {
                "aweme_info": {
                    "aweme_id": "7123456789012345678",
                    "desc": "团餐配送案例",
                    "author": {"uid": "1", "nickname": "作者"},
                    "statistics": {"digg_count": 10},
                }
            }
        ]
    }
    items = extract_aweme_items_from_json(data)
    assert len(items) == 1
    assert items[0]["aweme_id"] == "7123456789012345678"
    assert "video/" in items[0]["video_url"]


def test_douyin_publish_time_ui_label():
    from app.platforms.search_filters import douyin_publish_time_ui_label

    assert douyin_publish_time_ui_label(1) == "一天内"
    assert douyin_publish_time_ui_label(3) == "一周内"
    assert douyin_publish_time_ui_label(7) == "一周内"
    assert douyin_publish_time_ui_label(30) == "半年内"
    assert douyin_publish_time_ui_label(None) is None
    assert douyin_publish_time_ui_label(0) is None


def test_is_search_result_api():
    assert is_search_result_api("https://www.douyin.com/aweme/v1/web/general/search/single/")
    assert not is_search_result_api("https://www.douyin.com/aweme/v1/web/search/sug/")


def test_platform_skill_map_keyword_skill_flow():
    assert platform_for_skill_id("douyin-keyword-comments") == "douyin"
    assert crawl_skill_for_platform("douyin") == "douyin-keyword-comments"
