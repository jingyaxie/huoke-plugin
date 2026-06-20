from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QrLoginSession:
    session_id: str
    platform: str
    tenant_id: str
    account_id: str
    status: str = "pending"
    qr_image_url: str | None = None
    qr_image_base64: str | None = None
    qr_scan_url: str | None = None
    expires_at: float | None = None
    validity_hint: str = "二维码约 3 分钟内有效，过期后请重新获取"
    message: str | None = None
    poll_token: str | None = None
    qr_id: str | None = None
    qr_code: str | None = None
    created_at: float = field(default_factory=time.time)
    runtime: dict[str, Any] = field(default_factory=dict)
    poll_task: asyncio.Task | None = None


_sessions: dict[str, QrLoginSession] = {}
_index: dict[str, str] = {}


def _index_key(platform: str, tenant_id: str, account_id: str) -> str:
    return f"{platform}:{tenant_id}:{account_id}"


def create_session(platform: str, tenant_id: str, account_id: str) -> QrLoginSession:
    session = QrLoginSession(
        session_id=uuid.uuid4().hex,
        platform=platform,
        tenant_id=tenant_id,
        account_id=account_id,
    )
    _sessions[session.session_id] = session
    _index[_index_key(platform, tenant_id, account_id)] = session.session_id
    return session


def get_session(session_id: str) -> QrLoginSession | None:
    return _sessions.get(session_id)


def get_active_session(platform: str, tenant_id: str, account_id: str) -> QrLoginSession | None:
    sid = _index.get(_index_key(platform, tenant_id, account_id))
    if not sid:
        return None
    return _sessions.get(sid)


def remove_session(session_id: str) -> QrLoginSession | None:
    session = _sessions.pop(session_id, None)
    if session is None:
        return None
    key = _index_key(session.platform, session.tenant_id, session.account_id)
    if _index.get(key) == session_id:
        _index.pop(key, None)
    return session
