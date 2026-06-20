from __future__ import annotations

from app.services.agent_network_capture import compact_api_data_for_agent, compact_tool_result_for_llm


def test_compact_aweme_list_keeps_key_fields_only() -> None:
    raw = {
        "aweme_list": [
            {
                "aweme_id": "123",
                "desc": "篮球教学",
                "author": {"nickname": "杨教练", "uid": "999"},
                "statistics": {"digg_count": 8084, "comment_count": 119},
                "share_url": "https://www.douyin.com/video/123",
                "extra_blob": {"nested": True},
            }
        ],
        "log_pb": {"impr_id": "x"},
    }
    compact = compact_api_data_for_agent(raw, path="/aweme/v1/web/channel/hotspot")
    assert compact["_compact"] is True
    assert compact["_original_aweme_count"] == 1
    item = compact["aweme_list"][0]
    assert item["aweme_id"] == "123"
    assert item["author_name"] == "杨教练"
    assert item["digg_count"] == 8084
    assert "extra_blob" not in item
    assert "log_pb" not in compact


def test_compact_tool_result_for_network_data() -> None:
    result = {
        "count": 1,
        "items": [
            {
                "path": "/aweme/v1/web/channel/hotspot",
                "data": {
                    "aweme_list": [
                        {
                            "aweme_id": "7648234202216192997",
                            "desc": "罗斯哈达威变向",
                            "author": {"nickname": "左手 杨教练"},
                            "statistics": {"digg_count": 8084, "comment_count": 119},
                        }
                    ]
                },
            }
        ],
    }
    compact = compact_tool_result_for_llm("browser_get_network_data", result)
    item = compact["items"][0]["data"]["aweme_list"][0]
    assert item["aweme_id"] == "7648234202216192997"
    assert item["author_name"] == "左手 杨教练"
    assert "author" not in item
