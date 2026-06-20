from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.antibot import persistent_profile_enabled
from app.core.config import Settings
from app.platforms.douyin.session import DouyinSessionStore


@pytest.fixture
def douyin_store(tmp_path: Path) -> DouyinSessionStore:
    return DouyinSessionStore(
        Settings(storage_root=tmp_path, douyin_profile_dir=tmp_path / "douyin" / "profile")
    )


def test_persistent_profile_disabled_on_mac_desktop_mode() -> None:
    settings = Settings(desktop_mode=True, antibot_persistent_profile=True)
    assert persistent_profile_enabled(settings, "douyin") is False


def test_persistent_profile_disabled_on_mac_without_desktop() -> None:
    import platform as py_platform

    settings = Settings(
        desktop_mode=False,
        antibot_persistent_profile=True,
        antibot_browser_channel="chrome",
    )
    if py_platform.system() == "Darwin":
        assert persistent_profile_enabled(settings, "douyin") is False


def test_profile_has_user_data_detects_cookies_file(douyin_store: DouyinSessionStore) -> None:
    profile_default = douyin_store.profile_dir_for("default", "default") / "Default"
    profile_default.mkdir(parents=True)
    (profile_default / "Cookies").write_bytes(b"x" * 600)
    assert douyin_store.profile_has_user_data("default", "default") is True


def test_login_status_profile_ready_without_json(douyin_store: DouyinSessionStore) -> None:
    profile_default = douyin_store.profile_dir_for("default", "default") / "Default"
    profile_default.mkdir(parents=True)
    (profile_default / "Cookies").write_bytes(b"x" * 600)
    settings = douyin_store.settings.model_copy(update={"desktop_mode": True})
    douyin_store.settings = settings
    status = douyin_store.login_status("default", "default")
    assert status["status"] == "incomplete"
    assert status["profile_ready"] is True


def test_profile_needs_storage_seed_when_guest_profile(tmp_path: Path) -> None:
    import sqlite3

    store = DouyinSessionStore(
        Settings(storage_root=tmp_path, douyin_profile_dir=tmp_path / "douyin" / "profile")
    )
    profile_default = store.profile_dir_for("default", "default") / "Default"
    profile_default.mkdir(parents=True)
    cookies_path = profile_default / "Cookies"
    conn = sqlite3.connect(cookies_path)
    conn.execute(
        "CREATE TABLE cookies (name TEXT, host_key TEXT, value TEXT, path TEXT, expires_utc INTEGER)"
    )
    conn.execute(
        "INSERT INTO cookies VALUES (?, ?, ?, ?, ?)",
        ("IsDouyinActive", ".douyin.com", "1", "/", 0),
    )
    conn.commit()
    conn.close()

    state_path = store.path_for("default", "default")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "login_time", "value": "1", "domain": ".douyin.com", "path": "/"},
                    {"name": "passport_assist_user", "value": "1", "domain": ".douyin.com", "path": "/"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert store.profile_has_user_data("default", "default") is True
    assert store.profile_needs_storage_seed("default", "default") is True


def test_guest_sessionid_profile_does_not_satisfy_login_markers(douyin_store: DouyinSessionStore) -> None:
    import sqlite3

    profile_default = douyin_store.profile_dir_for("default", "default") / "Default"
    profile_default.mkdir(parents=True)
    cookies_path = profile_default / "Cookies"
    conn = sqlite3.connect(cookies_path)
    conn.execute(
        "CREATE TABLE cookies (name TEXT, host_key TEXT, value TEXT, path TEXT, expires_utc INTEGER)"
    )
    for name in ("sessionid", "uid_tt", "sid_tt"):
        conn.execute(
            "INSERT INTO cookies VALUES (?, ?, ?, ?, ?)",
            (name, ".douyin.com", "1", "/", 0),
        )
    conn.commit()
    conn.close()

    state_path = douyin_store.path_for("default", "default")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "login_time", "value": "1", "domain": ".douyin.com", "path": "/"},
                    {"name": "passport_assist_user", "value": "1", "domain": ".douyin.com", "path": "/"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert douyin_store.profile_satisfies_login_markers("default", "default") is False
    assert douyin_store.profile_needs_storage_seed("default", "default") is True
