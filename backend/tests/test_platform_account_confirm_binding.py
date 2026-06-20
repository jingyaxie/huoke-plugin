from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.platforms.douyin.session import DouyinSessionStore
from app.services.platform_account_store import PlatformAccountStore


@pytest.fixture
def store_bundle(tmp_path: Path):
    settings = Settings(storage_root=tmp_path, douyin_profile_dir=tmp_path / "douyin" / "profile")
    account_store = PlatformAccountStore(settings)
    douyin_store = DouyinSessionStore(settings)
    return account_store, douyin_store, settings


def test_confirm_platform_binding_updates_label_and_profile(store_bundle) -> None:
    account_store, douyin_store, settings = store_bundle
    douyin_store.save_dict(
        "default",
        {
            "cookies": [
                {"name": "sessionid", "value": "sid", "domain": ".douyin.com", "path": "/"},
                {"name": "uid_tt", "value": "99887766", "domain": ".douyin.com", "path": "/"},
                {"name": "login_time", "value": "1710000000", "domain": ".douyin.com", "path": "/"},
            ],
            "origins": [],
        },
        "default",
    )

    profile = account_store.confirm_platform_binding(
        "default",
        "default",
        "douyin",
        label="门店主号",
    )

    assert profile["cookie_ready"] is True
    assert profile["platform_user_id"] == "99887766"
    assert profile["label"] == "门店主号"
    assert profile["display_name"] == "门店主号"
    assert account_store.get_account("default", "default").label == "门店主号"


def test_platform_bindings_include_profile_fields(store_bundle) -> None:
    account_store, douyin_store, _settings = store_bundle
    douyin_store.save_dict(
        "default",
        {
            "cookies": [
                {"name": "sessionid", "value": "sid", "domain": ".douyin.com", "path": "/"},
                {"name": "uid_tt", "value": "11223344", "domain": ".douyin.com", "path": "/"},
                {"name": "login_time", "value": "1710000000", "domain": ".douyin.com", "path": "/"},
            ],
            "origins": [],
        },
        "default",
    )

    bindings = account_store.platform_bindings("default", "default")
    douyin = next(item for item in bindings if item.platform == "douyin")

    assert douyin.cookie_ready is True
    assert douyin.platform_user_id == "11223344"
    assert douyin.status == "ready"
