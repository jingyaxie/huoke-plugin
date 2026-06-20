from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from app.api.deps import get_account_id
from app.core.config import Settings, get_settings
from app.platforms.account_id import normalize_account_id
from app.platforms.tenant import normalize_tenant_id


def require_bridge_secret(
    x_bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not getattr(settings, "compat_enabled", True):
        raise HTTPException(status_code=503, detail="compat layer disabled")
    expected = (settings.huoke_bridge_secret or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="compat bridge secret not configured")
    provided = (x_bridge_secret or "").strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid bridge secret")


def compat_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    settings: Settings = Depends(get_settings),
) -> str:
    raw = (x_tenant_id or settings.default_tenant_id or "default").strip()
    try:
        return normalize_tenant_id(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def compat_account_id(account_id: str = Depends(get_account_id)) -> str:
    try:
        return normalize_account_id(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
