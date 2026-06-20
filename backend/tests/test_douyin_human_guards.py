from __future__ import annotations

import pytest

from app.core.config import Settings
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.douyin.human_guards import (
    HumanBrowseGuardError,
    _storage_login_status,
    is_blocked_douyin_host,
)


def test_storage_login_status_rejects_missing_cookies(tmp_path):
    settings = Settings(storage_root=tmp_path)
    store = DouyinSessionStore(settings)
    with pytest.raises(HumanBrowseGuardError, match="登录"):
        _storage_login_status(store, "default", "default")


def test_storage_login_status_accepts_session_cookies(tmp_path):
    settings = Settings(storage_root=tmp_path)
    store = DouyinSessionStore(settings)
    store.save_dict(
        "default",
        {
            "cookies": [
                {"name": "sessionid", "value": "x", "domain": ".douyin.com"},
                {"name": "login_time", "value": "1", "domain": ".douyin.com"},
            ]
        },
    )
    result = _storage_login_status(store, "default", "default")
    assert result["storage_ready"] is True
    assert result["logged_in"] is True


def test_is_blocked_douyin_host_detects_so_landing():
    assert is_blocked_douyin_host("https://so-landing.douyin.com/") is True
    assert is_blocked_douyin_host("https://www.douyin.com/jingxuan") is False
    assert is_blocked_douyin_host("") is False
