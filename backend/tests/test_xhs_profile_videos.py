from __future__ import annotations

import pytest

from app.platforms.xiaohongshu.profile_videos import is_user_posted_api, parse_profile_input_url
from app.services.manual_acquisition_service import reconcile_manual_acquisition_mode
from app.services.task_skill_playbook import skill_id_for_supervisor_action


PROFILE_URL = "https://www.xiaohongshu.com/user/profile/634157fa000000001802ff07"
NOTE_URL = (
    "https://www.xiaohongshu.com/explore/6a07f7370000000007021584"
    "?xsec_token=ABOTEYeuULo3_snyxN7TdSuJDEllpRQWBpKuZ0fnrfNmY=&xsec_source=pc_feed"
)


def test_parse_profile_url():
    parsed = parse_profile_input_url(PROFILE_URL)
    assert parsed["input_kind"] == "profile"
    assert parsed["user_id"] == "634157fa000000001802ff07"
    assert parsed["profile_url"].endswith(parsed["user_id"])


def test_parse_note_entry_url():
    parsed = parse_profile_input_url(NOTE_URL)
    assert parsed["input_kind"] == "note_entry"
    assert parsed["note_id"] == "6a07f7370000000007021584"
    assert parsed["xsec_token"]


def test_is_user_posted_api():
    assert is_user_posted_api("https://edith.xiaohongshu.com/api/sns/web/v1/user_posted?num=30")
    assert not is_user_posted_api("https://edith.xiaohongshu.com/api/sns/web/v2/comment/page")


def test_skill_playbook_maps_crawl_profile_to_xhs_skill():
    assert skill_id_for_supervisor_action("crawl_profile", "xiaohongshu") == "xhs-profile-comments"


def test_manual_account_home_keeps_explore_url():
    mode = reconcile_manual_acquisition_mode("account_home", NOTE_URL, "xiaohongshu")
    assert mode == "account_home"


def test_parse_invalid_url():
    with pytest.raises(ValueError):
        parse_profile_input_url("https://www.xiaohongshu.com/explore")
