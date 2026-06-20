from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Page

from app.platforms.qr_login_parsers import expires_in_seconds, utc_iso
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.constants import REQUIRED_LOGIN_COOKIES
from app.platforms.xiaohongshu.ui_helpers import fetch_user_me

AUTH_AUTHENTICATED = "authenticated"
AUTH_GUEST = "guest"
AUTH_EXPIRED = "expired"


def meta_path_for(store: PlatformSessionStore, tenant_id: str, account_id: str = "default"):
    return store.path_for(tenant_id, account_id).with_name("session_meta.json")


def load_meta(store: PlatformSessionStore, tenant_id: str, account_id: str = "default") -> dict[str, Any] | None:
    path = meta_path_for(store, tenant_id, account_id)
    if not path.exists():
        return None
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def save_meta(
    store: PlatformSessionStore,
    tenant_id: str,
    account_id: str,
    meta: dict[str, Any],
) -> None:
    path = meta_path_for(store, tenant_id, account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_meta(store: PlatformSessionStore, tenant_id: str, account_id: str = "default") -> bool:
    path = meta_path_for(store, tenant_id, account_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def compute_cookie_expires_at(state: dict | None) -> str | None:
    if not state:
        return None
    expires_values: list[float] = []
    for cookie in state.get("cookies") or []:
        if not isinstance(cookie, dict):
            continue
        if cookie.get("name") not in REQUIRED_LOGIN_COOKIES:
            continue
        raw = cookie.get("expires")
        if raw in (None, -1, 0):
            continue
        try:
            expires_values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not expires_values:
        return None
    return utc_iso(min(expires_values))


def cookie_expires_in_seconds(meta: dict | None, state: dict | None) -> int | None:
    expires_at = None
    if meta and meta.get("cookie_expires_at"):
        try:
            expires_at = datetime.fromisoformat(str(meta["cookie_expires_at"])).timestamp()
        except ValueError:
            expires_at = None
    if expires_at is None and state:
        for cookie in state.get("cookies") or []:
            if not isinstance(cookie, dict):
                continue
            if cookie.get("name") not in REQUIRED_LOGIN_COOKIES:
                continue
            raw = cookie.get("expires")
            if raw in (None, -1, 0):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            expires_at = value if expires_at is None else min(expires_at, value)
    return expires_in_seconds(expires_at)


def is_cookie_expired(meta: dict | None, state: dict | None) -> bool:
    remaining = cookie_expires_in_seconds(meta, state)
    return remaining is not None and remaining <= 0


def mark_session_expired(
    store: PlatformSessionStore,
    tenant_id: str,
    account_id: str,
    *,
    reason: str,
    detail: str | None = None,
) -> dict[str, Any]:
    meta = load_meta(store, tenant_id, account_id) or {}
    meta.update(
        {
            "auth_status": AUTH_EXPIRED,
            "guest": True,
            "expired_at": utc_iso(time.time()),
            "expired_reason": reason,
            "expired_detail": detail,
        }
    )
    save_meta(store, tenant_id, account_id, meta)
    return meta


async def record_authenticated_snapshot(
    store: PlatformSessionStore,
    tenant_id: str,
    account_id: str,
    page: Page | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    state = store.load(tenant_id, account_id) or {}
    resolved_user_id = user_id
    guest = False
    if page is not None:
        user_me = await fetch_user_me(page)
        guest = user_me.get("guest") is True
        resolved_user_id = resolved_user_id or user_me.get("user_id")
    now = utc_iso(time.time())
    meta = {
        "auth_status": AUTH_GUEST if guest else AUTH_AUTHENTICATED,
        "guest": guest,
        "user_id": resolved_user_id,
        "saved_at": now,
        "verified_at": now,
        "cookie_expires_at": compute_cookie_expires_at(state),
        "expired_at": None,
        "expired_reason": None,
        "expired_detail": None,
    }
    save_meta(store, tenant_id, account_id, meta)
    return meta


def derive_auth_status(
    *,
    has_cookies: bool,
    meta: dict[str, Any] | None,
    state: dict | None,
) -> str:
    if not has_cookies:
        return "missing"
    if not meta:
        if state and _has_required_cookies(state):
            return AUTH_GUEST
        return "incomplete"
    if meta.get("auth_status") == AUTH_EXPIRED:
        return AUTH_EXPIRED
    if is_cookie_expired(meta, state):
        return AUTH_EXPIRED
    if meta.get("auth_status") == AUTH_AUTHENTICATED and meta.get("guest") is False:
        return AUTH_AUTHENTICATED
    if meta.get("guest") is True:
        return AUTH_GUEST
    if _has_required_cookies(state):
        return AUTH_GUEST
    return "incomplete"


def _has_required_cookies(state: dict | None) -> bool:
    if not state:
        return False
    cookie_names = {c.get("name") for c in state.get("cookies", []) if isinstance(c, dict)}
    return "web_session" in cookie_names and bool(cookie_names & REQUIRED_LOGIN_COOKIES)


def enrich_login_status(
    store: PlatformSessionStore,
    tenant_id: str,
    account_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    state = store.load(tenant_id, account_id) or {}
    meta = load_meta(store, tenant_id, account_id)
    has_cookies = bool(state.get("cookies"))
    auth_status = derive_auth_status(has_cookies=has_cookies, meta=meta, state=state)
    cookie_expires_at = (meta or {}).get("cookie_expires_at") or compute_cookie_expires_at(state)
    remaining = cookie_expires_in_seconds(meta, state)

    result["auth_status"] = auth_status
    result["session_meta"] = meta
    result["cookie_expires_at"] = cookie_expires_at
    result["cookie_expires_in_seconds"] = remaining
    result["needs_relogin"] = auth_status in {AUTH_EXPIRED, AUTH_GUEST, "incomplete", "missing"}

    if auth_status == AUTH_EXPIRED:
        result["status"] = "expired"
        reason = (meta or {}).get("expired_reason") or "cookie_expired"
        result["message"] = {
            "guest": "登录态已失效（游客态），请重新扫码登录",
            "cookie_expired": "登录 Cookie 已过期，请重新扫码登录",
            "live_verify_failed": "在线校验失败，登录态可能已过期，请重新扫码登录",
            "activate_failed": "会话激活失败，请重新扫码登录",
        }.get(str(reason), "登录态已过期，请重新扫码登录")
    elif auth_status == AUTH_AUTHENTICATED:
        result["status"] = "authenticated"
        result["message"] = "登录态有效"
        if remaining is not None and remaining <= 3600:
            result["message"] = f"登录态有效，Cookie 约 {max(1, remaining // 60)} 分钟后过期"
    elif auth_status == AUTH_GUEST:
        result["status"] = "guest"
        result["message"] = "当前为游客态或未验证真实登录，请重新扫码登录"

    meta_user_id = str((meta or {}).get("user_id") or "").strip()
    if meta_user_id:
        result["platform_user_id"] = meta_user_id
        result["account_id"] = meta_user_id
        result["uid"] = meta_user_id

    return result
