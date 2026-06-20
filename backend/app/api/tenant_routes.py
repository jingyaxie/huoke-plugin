from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_authenticated_tenant_id, require_current_user
from app.core.config import Settings, get_settings
from app.models.user import User
from app.schemas.auth import TenantOut
from app.services.user_auth_service import UserAuthService

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


@router.get("/me", response_model=TenantOut)
def get_current_tenant(
    current_user: User = Depends(require_current_user),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TenantOut:
    if current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="租户上下文与登录用户不一致")
    auth = UserAuthService(session, settings)
    tenant = auth.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="租户不存在")
    return auth.to_tenant_out(tenant)


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(
    tenant_id: str,
    current_user: User = Depends(require_current_user),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> TenantOut:
    if current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权查看其他租户")
    auth = UserAuthService(session, settings)
    tenant = auth.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="租户不存在")
    return auth.to_tenant_out(tenant)
