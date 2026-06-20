from __future__ import annotations

import pytest

from app.services.ui_flow.platforms.douyin.profile_ui import on_profile_url


def test_on_profile_url():
    assert on_profile_url("https://www.douyin.com/user/MS4wLjABAAAAtest")
    assert not on_profile_url("https://www.douyin.com/video/7123456789012345678")
    assert not on_profile_url("https://www.douyin.com/search/AI")
