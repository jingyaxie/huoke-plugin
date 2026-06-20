from __future__ import annotations

import pytest

from app.services.ui_flow.platforms.douyin.feed_ui import (
    comment_list_end_marker_visible,
    merge_comment_api_pages,
)


class _FakeLocator:
    def __init__(self, *, count: int, visible: bool) -> None:
        self._count = count
        self._visible = visible

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible


class _FakePage:
    def __init__(self, markers: list[tuple[int, bool]]) -> None:
        self._markers = markers
        self._idx = 0

    def get_by_text(self, text: str, *, exact: bool = False):
        idx = self._idx
        self._idx += 1
        if idx < len(self._markers):
            count, visible = self._markers[idx]
            return _FakeLocator(count=count, visible=visible)
        return _FakeLocator(count=0, visible=False)


@pytest.mark.asyncio
async def test_comment_list_end_marker_visible_detects_footer():
    page = _FakePage([(1, True), (0, False)])
    assert await comment_list_end_marker_visible(page) is True


@pytest.mark.asyncio
async def test_comment_list_end_marker_visible_false_when_absent():
    page = _FakePage([(0, False), (0, False)])
    assert await comment_list_end_marker_visible(page) is False


def _sample_page(cid: str, text: str, *, replies: list[dict] | None = None) -> dict:
    return {
        "total": 100,
        "comments": [
            {
                "cid": cid,
                "text": text,
                "create_time": 100,
                "digg_count": 1,
                "reply_comment_total": len(replies or []),
                "reply_comment": replies or [],
                "user": {"uid": "1", "nickname": "u1", "sec_uid": "s1"},
            }
        ],
    }


def test_merge_comment_api_pages_deduplicates_and_limits():
    page1 = _sample_page("c1", "第一条")
    page2 = {
        "total": 100,
        "comments": [
            {
                "cid": "c2",
                "text": "第二条",
                "create_time": 90,
                "digg_count": 0,
                "reply_comment_total": 0,
                "reply_comment": [],
                "user": {"uid": "2", "nickname": "u2", "sec_uid": "s2"},
            },
            {
                "cid": "c1",
                "text": "重复",
                "create_time": 99,
                "digg_count": 0,
                "reply_comment_total": 0,
                "reply_comment": [],
                "user": {"uid": "2", "nickname": "u2", "sec_uid": "s2"},
            },
        ],
    }
    _, api_total, top_rows = merge_comment_api_pages([page1, page2], max_comments=1)
    assert api_total == 100
    assert len(top_rows) == 1
    assert top_rows[0]["comment_id"] == "c1"


def test_merge_comment_api_pages_includes_preview_replies():
    replies = [
        {
            "cid": "r1",
            "text": "回复内容",
            "create_time": 50,
            "digg_count": 0,
            "user": {"uid": "3", "nickname": "u3", "sec_uid": "s3"},
        }
    ]
    page = _sample_page("c1", "主评", replies=replies)
    comments_map, _, top_rows = merge_comment_api_pages([page], max_comments=5)
    assert len(top_rows) == 1
    assert "r1" in comments_map
    assert comments_map["r1"]["parent_comment_id"] == "c1"
