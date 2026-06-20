from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_current_user
from app.core.config import Settings, get_settings
from app.models.user import User
from app.schemas.auth import (
    AuthTokenResponse,
    BridgeAuthRequest,
    LoginRequest,
    RegisterRequest,
    TenantOut,
    UserOut,
)
from app.services.user_auth_service import UserAuthError, UserAuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=AuthTokenResponse)
def register(
    payload: RegisterRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> AuthTokenResponse:
    auth = UserAuthService(session, settings)
    try:
        user, tenant = auth.register(payload)
        session.commit()
    except UserAuthError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token, expires_in = auth.create_access_token(user)
    return AuthTokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=auth.to_user_out(user),
        tenant=auth.to_tenant_out(tenant),
    )


@router.post("/bridge", response_model=AuthTokenResponse)
def bridge_auth(
    payload: BridgeAuthRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
    x_huoke_bridge_secret: str | None = Header(default=None, alias="X-Huoke-Bridge-Secret"),
) -> AuthTokenResponse:
    secret = (settings.huoke_bridge_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Huoke bridge 未配置")
    if (x_huoke_bridge_secret or "").strip() != secret:
        raise HTTPException(status_code=403, detail="无效的 bridge secret")

    auth = UserAuthService(session, settings)
    register_payload = RegisterRequest(
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name or payload.username,
        tenant_id=payload.tenant_id,
        tenant_name=payload.tenant_name or payload.tenant_id,
    )
    try:
        user, tenant = auth.provision_bridge_user(register_payload)
        session.commit()
    except UserAuthError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token, expires_in = auth.create_access_token(user)
    return AuthTokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=auth.to_user_out(user),
        tenant=auth.to_tenant_out(tenant),
    )


@router.post("/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> AuthTokenResponse:
    auth = UserAuthService(session, settings)
    try:
        user = auth.login(payload.username, payload.password)
        tenant = auth.get_tenant(user.tenant_id)
        if tenant is None:
            raise UserAuthError("所属租户不存在")
        session.commit()
    except UserAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token, expires_in = auth.create_access_token(user)
    return AuthTokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=auth.to_user_out(user),
        tenant=auth.to_tenant_out(tenant),
    )


@router.get("/me")
def auth_me(
    user: User = Depends(require_current_user),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    auth = UserAuthService(session, settings)
    tenant = auth.get_tenant(user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="租户不存在")
    return {
        "user": auth.to_user_out(user),
        "tenant": auth.to_tenant_out(tenant),
    }
