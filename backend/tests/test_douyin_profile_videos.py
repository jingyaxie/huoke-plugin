from __future__ import annotations

import pytest

from app.platforms.douyin.profile_videos import (
    is_douyin_short_url,
    is_profile_post_api,
    parse_profile_input_url,
    resolve_douyin_short_url,
)


TEST_PROFILE_URL = (
    "https://www.douyin.com/user/MS4wLjABAAAAI2P_yBUDrjJccqUniIzrnsKv-4wl9mtiUbeXApqenH5fWzgyo9hEBV6GqKzKV334"
    "?from_tab_name=main&vid=7617663855346404617"
)


def test_parse_profile_url_with_vid():
    parsed = parse_profile_input_url(TEST_PROFILE_URL)
    assert parsed["input_kind"] == "profile"
    assert parsed["sec_uid"].startswith("MS4w")
    assert parsed["vid"] == "7617663855346404617"
    assert "vid=7617663855346404617" in parsed["profile_url"]


def test_parse_single_video_url():
    parsed = parse_profile_input_url("https://www.douyin.com/video/7617663855346404617")
    assert parsed["input_kind"] == "single_video"
    assert parsed["vid"] == "7617663855346404617"


def test_is_profile_post_api():
    assert is_profile_post_api(
        "https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id=MS4w"
    )
    assert not is_profile_post_api("https://www.douyin.com/aweme/v1/web/general/search/single/")


def test_parse_profile_url_missing_user():
    with pytest.raises(ValueError):
        parse_profile_input_url("https://www.douyin.com/hot")


def test_is_douyin_short_url():
    assert is_douyin_short_url("https://v.douyin.com/fDELcUzXDCA/")
    assert not is_douyin_short_url("https://www.douyin.com/user/MS4w")


def test_resolve_douyin_short_url_to_profile():
    location = resolve_douyin_short_url("https://v.douyin.com/fDELcUzXDCA/")
    assert location
    assert "iesdouyin.com/share/user/" in location or "douyin.com/user/" in location


def test_parse_douyin_short_profile_url():
    parsed = parse_profile_input_url("https://v.douyin.com/fDELcUzXDCA/")
    assert parsed["input_kind"] == "profile"
    assert parsed["sec_uid"].startswith("MS4w")
    assert parsed["profile_url"].startswith("https://www.douyin.com/user/")


def test_skill_playbook_maps_crawl_profile_to_douyin_skill():
    from app.services.task_skill_playbook import skill_id_for_supervisor_action

    assert skill_id_for_supervisor_action("crawl_profile", "douyin") == "douyin-profile-comments"
