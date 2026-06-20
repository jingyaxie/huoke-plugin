from __future__ import annotations

from app.services.supervisor_outreach_helpers import (
    build_reply_text,
    count_crawl_comments,
    crawl_search_phase_succeeded,
    extract_crawl_payloads,
    validate_crawl_skill_result,
)
from app.services.task_brief_service import TaskBrief
from app.services.task_skill_playbook import skill_id_for_supervisor_action


def test_skill_id_for_supervisor_action_crawl_by_platform():
    assert skill_id_for_supervisor_action("crawl_keyword", "douyin") == "douyin-keyword-comments"
    assert skill_id_for_supervisor_action("reply", "douyin") == "reply-comment"


def test_extract_crawl_payloads_from_agent_result():
    skill_result = {
        "result": {
            "comments_by_video": [
                {
                    "video_url": "https://www.douyin.com/video/7123456789012345678",
                    "comments": [
                        {
                            "comment_id": "c1",
                            "comment": "团餐配送多少钱",
                            "username": "用户A",
                        }
                    ],
                }
            ]
        }
    }
    payloads = extract_crawl_payloads(skill_result)
    assert len(payloads) == 1
    assert payloads[0]["aweme_id"] == "7123456789012345678"
    assert payloads[0]["comments"][0]["comment_id"] == "c1"


def test_build_reply_text_uses_brief_template():
    brief = TaskBrief(
        platform="douyin",
        constraints={"reply_template": "你好 {{nickname}}，关于{{comment}}我们可以聊聊"},
    )
    text = build_reply_text(brief, nickname="小王", comment="报价多少")
    assert "小王" in text
    assert "报价多少" in text


def test_persist_crawl_skill_result_empty_returns_zero():
    assert extract_crawl_payloads({}) == []


def test_validate_crawl_skill_result_rejects_metadata_only():
    ok, err, count = validate_crawl_skill_result(
        {
            "status": "completed",
            "result": {
                "comments_collected": 9,
                "videos": [{"sample_comment": "test"}],
                "comments_by_video": [],
            },
        }
    )
    assert ok is False
    assert count == 0
    assert "结构化" in err or "comments" in err


def test_validate_crawl_skill_result_accepts_search_phase_only():
    ok, err, count = validate_crawl_skill_result(
        {
            "status": "partial",
            "videos_processed": 0,
            "total_comments_captured": 0,
            "search_succeeded": True,
            "search_url": "https://www.douyin.com/jingxuan/search/淋浴房",
            "discovered_video_urls": [
                "https://www.douyin.com/video/7123456789012345678",
            ],
            "discovered_video_count": 1,
            "results": [],
        }
    )
    assert ok is True
    assert err == ""
    assert count == 0


def test_crawl_search_phase_succeeded_requires_urls_or_count():
    assert crawl_search_phase_succeeded(
        {
            "search_succeeded": True,
            "search_url": "https://www.douyin.com/jingxuan/search/kw",
            "discovered_video_urls": ["https://www.douyin.com/video/1"],
        }
    )
    assert crawl_search_phase_succeeded(
        {
            "search_succeeded": True,
            "search_url": "https://www.xiaohongshu.com/search_result?keyword=淋浴房",
            "discovered_video_urls": [
                "https://www.xiaohongshu.com/explore/abc123",
            ],
        }
    )
    assert not crawl_search_phase_succeeded(
        {
            "search_succeeded": True,
            "search_url": "https://www.douyin.com/jingxuan/search/kw",
            "discovered_video_urls": [],
            "discovered_video_count": 0,
        }
    )
    assert not crawl_search_phase_succeeded({"search_succeeded": False})


def test_validate_crawl_skill_result_accepts_xhs_search_phase_only():
    ok, err, count = validate_crawl_skill_result(
        {
            "status": "partial",
            "platform": "xiaohongshu",
            "videos_processed": 0,
            "total_comments_captured": 0,
            "search_succeeded": True,
            "search_url": "https://www.xiaohongshu.com/search_result?keyword=淋浴房",
            "discovered_video_urls": [
                "https://www.xiaohongshu.com/explore/5f8a1b2c3d4e5f6a7b8c9d0e",
            ],
            "discovered_video_count": 1,
            "results": [],
        }
    )
    assert ok is True
    assert err == ""
    assert count == 0


def test_validate_crawl_skill_result_accepts_structured_comments():
    ok, err, count = validate_crawl_skill_result(
        {
            "result": {
                "comments_by_video": [
                    {
                        "video_url": "https://www.douyin.com/video/7123456789012345678",
                        "comments": [{"comment_id": "c1", "comment": "团餐多少钱"}],
                    }
                ]
            }
        }
    )
    assert ok is True
    assert err == ""
    assert count == 1
    assert (
        count_crawl_comments(
            {
                "result": {
                    "comments_by_video": [
                        {
                            "video_url": "https://www.douyin.com/video/7123456789012345678",
                            "comments": [{"comment_id": "a"}, {"comment_id": "b"}],
                        }
                    ]
                }
            }
        )
        == 2
    )
