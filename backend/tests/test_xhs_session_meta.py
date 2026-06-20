from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.core.config import Settings
from app.platforms.xiaohongshu.session import XhsSessionStore
from app.platforms.xiaohongshu.session_meta import (
    AUTH_AUTHENTICATED,
    AUTH_EXPIRED,
    AUTH_GUEST,
    compute_cookie_expires_at,
    derive_auth_status,
    enrich_login_status,
    mark_session_expired,
    save_meta,
)


@pytest.fixture
def xhs_store(tmp_path: Path) -> XhsSessionStore:
    settings = Settings(storage_root=tmp_path)
    return XhsSessionStore(settings)


def _write_state(store: XhsSessionStore, tenant_id: str, account_id: str = "default") -> None:
    state = {
        "cookies": [
            {
                "name": "web_session",
                "value": "abc",
                "domain": ".xiaohongshu.com",
                "path": "/",
                "expires": time.time() + 3600,
            },
            {"name": "a1", "value": "a1", "domain": ".xiaohongshu.com", "path": "/"},
            {"name": "webId", "value": "web", "domain": ".xiaohongshu.com", "path": "/"},
        ],
        "origins": [],
    }
    store.save_dict(tenant_id, state, account_id)


def test_derive_auth_status_guest_without_meta(xhs_store: XhsSessionStore) -> None:
    _write_state(xhs_store, "default")
    state = xhs_store.load("default", "default")
    assert derive_auth_status(has_cookies=True, meta=None, state=state) == AUTH_GUEST


def test_login_status_marks_expired_from_meta(xhs_store: XhsSessionStore) -> None:
    _write_state(xhs_store, "default")
    mark_session_expired(xhs_store, "default", "default", reason="guest")
    status = xhs_store.login_status("default", "default")
    assert status["status"] == "expired"
    assert status["auth_status"] == AUTH_EXPIRED
    assert status["needs_relogin"] is True


def test_login_status_authenticated_with_meta(xhs_store: XhsSessionStore) -> None:
    _write_state(xhs_store, "default")
    save_meta(
        xhs_store,
        "default",
        "default",
        {
            "auth_status": AUTH_AUTHENTICATED,
            "guest": False,
            "user_id": "user123",
            "saved_at": "2026-06-12T00:00:00+00:00",
            "verified_at": "2026-06-12T00:00:00+00:00",
            "cookie_expires_at": compute_cookie_expires_at(xhs_store.load("default", "default")),
        },
    )
    status = xhs_store.login_status("default", "default")
    assert status["status"] == "authenticated"
    assert status["auth_status"] == AUTH_AUTHENTICATED
    assert status["needs_relogin"] is False
    assert status["platform_user_id"] == "user123"
    assert status["account_id"] == "user123"
    assert xhs_store.is_usable("default", "default") is True


def test_cookie_expired_status(xhs_store: XhsSessionStore) -> None:
    expired_state = {
        "cookies": [
            {
                "name": "web_session",
                "value": "abc",
                "domain": ".xiaohongshu.com",
                "path": "/",
                "expires": time.time() - 60,
            },
            {"name": "a1", "value": "a1", "domain": ".xiaohongshu.com", "path": "/"},
            {"name": "webId", "value": "web", "domain": ".xiaohongshu.com", "path": "/"},
        ]
    }
    xhs_store.save_dict("default", expired_state, "default")
    save_meta(
        xhs_store,
        "default",
        "default",
        {
            "auth_status": AUTH_AUTHENTICATED,
            "guest": False,
            "cookie_expires_at": compute_cookie_expires_at(expired_state),
        },
    )
    status = enrich_login_status(
        xhs_store,
        "default",
        "default",
        xhs_store.login_status("default", "default"),
    )
    assert status["auth_status"] == AUTH_EXPIRED
    assert status["status"] == "expired"


def test_clear_session_removes_meta(xhs_store: XhsSessionStore) -> None:
    _write_state(xhs_store, "default")
    mark_session_expired(xhs_store, "default", "default", reason="guest")
    xhs_store.clear_session("default", "default")
    assert xhs_store.load("default", "default") is None
    meta_path = xhs_store.path_for("default", "default").with_name("session_meta.json")
    assert meta_path.exists() is False
