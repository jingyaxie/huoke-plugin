from app.platforms.douyin.follow import _is_followed_status
from app.platforms.xiaohongshu.follow import _parse_follow_status


def test_douyin_is_followed_status():
    assert _is_followed_status(0) is False
    assert _is_followed_status(1) is True
    assert _is_followed_status(2) is True


def test_xhs_parse_follow_status():
    assert _parse_follow_status({"followed": True}) == "followed"
    assert _parse_follow_status({"follow_status": 0}) == "none"
    assert _parse_follow_status({}) == "unknown"
