from __future__ import annotations

from app.services.outreach_matcher import match_spec, render_template, resolve_follow_match
from app.services.outreach_normalizer import normalize_crawl_results


def test_match_spec_keyword():
    spec = {"mode": "keyword", "keywords": ["多少钱", "报价"], "min_comment_length": 2}
    ok, reason = match_spec("这个多少钱呀", spec)
    assert ok is True
    assert reason.startswith("keyword:")
    ok2, _ = match_spec("好厉害", spec)
    assert ok2 is False


def test_resolve_follow_match_independent():
    comment_match = {"mode": "keyword", "keywords": ["多少钱"]}
    follow_match = {"mode": "keyword", "keywords": ["想装"]}
    ok_reply, _ = match_spec("多少钱", comment_match)
    ok_follow, _ = resolve_follow_match("想装淋浴房", comment_match, follow_match)
    assert ok_reply is True
    assert ok_follow is True
    ok_follow2, _ = resolve_follow_match("多少钱", comment_match, follow_match)
    assert ok_follow2 is False


def test_normalize_crawl_results():
    results = [
        {
            "aweme_id": "7123456789",
            "video_url": "https://www.douyin.com/video/7123456789",
            "comments": [
                {
                    "comment_id": "c1",
                    "comment": "多少钱",
                    "nickname": "用户A",
                    "user_id": "u1",
                    "sec_uid": "sec1",
                }
            ],
        }
    ]
    leads = normalize_crawl_results(results, task_id="t1", keyword="淋浴房", platform="douyin")
    assert len(leads) == 1
    assert leads[0]["comment"]["comment_id"] == "c1"
    assert leads[0]["comment_user"]["user_id"] == "u1"


def test_render_template():
    text = render_template("你好 {{nickname}}，看到您问{{comment}}", nickname="小王", comment="价格")
    assert "小王" in text
    assert "价格" in text
