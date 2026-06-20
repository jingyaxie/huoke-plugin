from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.platforms.douyin.session import DouyinSessionStore


@pytest.fixture
def douyin_store(tmp_path: Path) -> DouyinSessionStore:
    return DouyinSessionStore(
        Settings(storage_root=tmp_path, douyin_profile_dir=tmp_path / "douyin" / "profile")
    )


def test_login_status_includes_platform_user_id_from_uid_tt_cookie(douyin_store: DouyinSessionStore) -> None:
    douyin_store.save_dict(
        "default",
        {
            "cookies": [
                {"name": "sessionid", "value": "sid", "domain": ".douyin.com", "path": "/"},
                {"name": "uid_tt", "value": "7123456789", "domain": ".douyin.com", "path": "/"},
                {"name": "login_time", "value": "1710000000", "domain": ".douyin.com", "path": "/"},
            ],
            "origins": [],
        },
        "default",
    )
    status = douyin_store.login_status("default", "default")
    assert status["status"] == "ready"
    assert status["user_logged_in"] is True
    assert status["platform_user_id"] == "7123456789"
    assert status["account_id"] == "default"
