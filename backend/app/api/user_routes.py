from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_authenticated_tenant_id, require_current_user
from app.core.config import Settings, get_settings
from app.models.user import User
from app.schemas.auth import UserListResponse, UserOut
from app.services.user_auth_service import UserAuthService

router = APIRouter(prefix="/api/users", tags=["users"])


def _ensure_same_tenant(requester: User, target: User) -> None:
    if requester.tenant_id != target.tenant_id:
        raise HTTPException(status_code=403, detail="无权查看其他租户的用户")


@router.get("", response_model=UserListResponse)
def list_users(
    current_user: User = Depends(require_current_user),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> UserListResponse:
    if current_user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="租户上下文与登录用户不一致")
    auth = UserAuthService(session, settings)
    items = [auth.to_user_out(u) for u in auth.list_users_in_tenant(tenant_id)]
    return UserListResponse(items=items, total=len(items))


@router.get("/me", response_model=UserOut)
def get_current_user_profile(
    current_user: User = Depends(require_current_user),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    return UserAuthService.to_user_out(current_user)


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    current_user: User = Depends(require_current_user),
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    auth = UserAuthService(session, settings)
    target = auth.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    _ensure_same_tenant(current_user, target)
    return auth.to_user_out(target)
