from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.platforms.types import platform_from_content_url
from app.schemas.skill import SkillOut
from app.services.skill_executor import SkillExecutor
from app.services.platform_skill_map import platform_for_skill_id


def _skill(skill_id: str, handler: str = "crawl_keyword_comments") -> SkillOut:
    return SkillOut(
        id=skill_id,
        name=skill_id,
        description="test",
        type="builtin",
        builtin_handler=handler,
        tool_name=f"skill_{skill_id.replace('-', '_')}",
    )


def test_platform_from_content_url():
    assert platform_from_content_url("https://www.kuaishou.com/short-video/3x6jthbgnbjnfm4") == "kuaishou"
    assert platform_from_content_url("https://www.douyin.com/video/7123456789012345678") == "douyin"
    assert platform_from_content_url("https://www.xiaohongshu.com/explore/abc123") == "xiaohongshu"
    assert platform_from_content_url("https://example.com/foo") is None


def test_platform_for_skill_id_maps_keyword_skills():
    assert platform_for_skill_id("kuaishou-keyword-comments") == "kuaishou"
    assert platform_for_skill_id("douyin-keyword-comments") == "douyin"
    assert platform_for_skill_id("xhs-keyword-comments") == "xiaohongshu"
    assert platform_for_skill_id("follow-user") is None


def test_skill_executor_resolves_platform_from_skill_id():
    session = MagicMock()
    session.account_id = "default"
    executor = SkillExecutor(
        settings=MagicMock(),
        tenant_id="default",
        platform="douyin",
        session=session,
        pw_executor=MagicMock(),
    )
    assert executor._resolve_platform(_skill("kuaishou-keyword-comments")) == "kuaishou"
    assert executor._resolve_platform(_skill("follow-user", handler="follow_user")) == "douyin"


@pytest.mark.asyncio
async def test_kuaishou_keyword_skill_uses_kuaishou_crawler(monkeypatch):
    session = MagicMock()
    session.account_id = "default"
    session.is_started = False
    executor = SkillExecutor(
        settings=MagicMock(),
        tenant_id="default",
        platform="douyin",
        session=session,
        pw_executor=MagicMock(),
    )

    captured: dict[str, str] = {}

    class FakeService:
        def __init__(self, settings, tenant_id, platform, account_id, session=None):
            captured["platform"] = platform

        async def crawl_keyword_comments(self, **kwargs):
            return (
                [{"video_url": "https://www.kuaishou.com/short-video/abc", "total_comments_captured": 0}],
                [],
                None,
                {"session_mode": "logged_in"},
                None,
            )

    monkeypatch.setattr("app.services.skill_executor.CommentCrawlerService", FakeService)

    result = await executor.execute(
        _skill("kuaishou-keyword-comments"),
        {"keyword": "吉林淋浴房"},
    )

    assert captured["platform"] == "kuaishou"
    assert result.get("platform") == "kuaishou"
    assert "kuaishou.com" in result["results"][0]["video_url"]


@pytest.mark.asyncio
async def test_content_comments_uses_platform_from_kuaishou_url(monkeypatch):
    session = MagicMock()
    session.account_id = "default"
    session.is_started = False
    executor = SkillExecutor(
        settings=MagicMock(),
        tenant_id="default",
        platform="douyin",
        session=session,
        pw_executor=MagicMock(),
    )

    captured: dict[str, str] = {}
    ks_url = "https://www.kuaishou.com/short-video/3x6jthbgnbjnfm4"

    class FakeService:
        def __init__(self, settings, tenant_id, platform, account_id, session=None):
            captured["platform"] = platform

        async def crawl_video_comments(self, video_url, **kwargs):
            assert video_url == ks_url
            return (
                {
                    "video_url": ks_url,
                    "photo_id": "3x6jthbgnbjnfm4",
                    "total_comments_captured": 3,
                    "comments": [],
                },
                __import__("pathlib").Path("/tmp/comments.json"),
                None,
            )

    monkeypatch.setattr("app.services.skill_executor.CommentCrawlerService", FakeService)

    result = await executor.execute(
        _skill("content-comments", handler="crawl_video_comments"),
        {"video_url": ks_url},
    )

    assert captured["platform"] == "kuaishou"
    assert result.get("platform") == "kuaishou"
    assert result.get("status") == "completed"
