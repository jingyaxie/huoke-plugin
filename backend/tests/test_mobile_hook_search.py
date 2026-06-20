from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platforms.douyin.mobile_hook_client import DouyinMobileHookClient
from app.platforms.douyin.mobile_hook_search import extract_hook_videos, normalize_hook_video, probe_bridge


def test_normalize_hook_video_maps_huoke_schema():
    raw = {
        "aweme_id": "7616001617523354532",
        "desc": "足浴养生",
        "share_url": "https://www.iesdouyin.com/share/video/7616001617523354532",
        "author": {"nickname": "测试用户", "uid": "123", "sec_uid": "sec_abc"},
        "statistics": {"digg_count": 100, "comment_count": 5, "share_count": 1},
    }
    video = normalize_hook_video(raw)
    assert video["aweme_id"] == "7616001617523354532"
    assert video["title"] == "足浴养生"
    assert video["author"] == "测试用户"
    assert video["like_count"] == 100
    assert "douyin.com/video/" in video["video_url"]


def test_extract_hook_videos_from_bridge_payload():
    payload = {
        "success": True,
        "videos": [
            {"aweme_id": "1", "desc": "a", "author": {"nickname": "n"}, "statistics": {}},
        ],
    }
    rows = extract_hook_videos(payload)
    assert len(rows) == 1
    assert rows[0]["aweme_id"] == "1"


@pytest.mark.asyncio
async def test_probe_bridge_disabled():
    settings = MagicMock()
    settings.douyin_mobile_hook_enabled = False
    out = await probe_bridge(settings)
    assert out["ok"] is False
    assert out["error"] == "mobile_hook_disabled"


@pytest.mark.asyncio
async def test_douyin_mobile_hook_client_probe_ready():
    client = DouyinMobileHookClient(auto_forward=False, token="test-token")

    async def fake_health():
        return {"success": True, "adapter": {"ready": True}}

    with patch.object(client, "health", new=AsyncMock(side_effect=fake_health)):
        result = await client.probe()
    assert result.ready is True
    assert result.ok is True
