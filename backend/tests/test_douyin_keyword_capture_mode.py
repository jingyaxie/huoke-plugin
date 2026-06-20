"""Douyin keyword crawl accepts capture_mode from skill_flow supervisor."""

from __future__ import annotations

import inspect

from app.platforms.douyin.comments import DouyinCommentCrawler


def test_crawl_keyword_comments_accepts_capture_mode():
    sig = inspect.signature(DouyinCommentCrawler.crawl_keyword_comments)
    assert "capture_mode" in sig.parameters
