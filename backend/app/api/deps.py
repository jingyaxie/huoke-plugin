from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User
from app.platforms.registry import get_session_store
from app.platforms.session_store import PlatformSessionStore
from app.platforms.account_id import normalize_account_id
from app.platforms.tenant import normalize_tenant_id
from app.platforms.types import normalize_platform
from app.services.tenant_auth_service import TenantAuthService
from app.services.user_auth_service import UserAuthError, UserAuthService


def db_session(session: Session = Depends(get_db)) -> Session:
    return session


def get_platform_id(
    x_platform_id: str | None = Header(default=None, alias="X-Platform-Id"),
    platform: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    raw = x_platform_id or platform or settings.default_platform
    try:
        return normalize_platform(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_path_platform_id(platform: str) -> str:
    try:
        return normalize_platform(platform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_account_id(
    x_account_id: str | None = Header(default=None, alias="X-Account-Id"),
    query_account_id: str | None = Query(default=None, alias="account_id"),
) -> str:
    raw = (x_account_id or query_account_id or "default").strip()
    try:
        return normalize_account_id(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    auth = UserAuthService(session, settings)
    try:
        payload = auth.decode_access_token(token)
        user = auth.get_user_by_id(int(payload["sub"]))
    except (UserAuthError, ValueError, KeyError):
        return None
    if user is None or not user.is_active:
        return None
    return user


def require_current_user(
    user: User | None = Depends(get_current_user),
) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def get_authenticated_tenant_id(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    query_tenant_id: str | None = Query(default=None, alias="tenant_id"),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> str:
    token = _extract_bearer_token(authorization)
    if token:
        auth = UserAuthService(session, settings)
        try:
            payload = auth.decode_access_token(token)
            user = auth.get_user_by_id(int(payload["sub"]))
            if user is not None and user.is_active:
                return user.tenant_id
            if settings.tenant_auth_enabled:
                raise HTTPException(status_code=401, detail="登录用户无效或已禁用")
        except (UserAuthError, ValueError, KeyError) as exc:
            if settings.tenant_auth_enabled:
                raise HTTPException(status_code=401, detail="无效或已过期的登录令牌") from exc
        # 未启用租户鉴权时，过期/无效登录令牌回退到 X-Tenant-Id，避免抓取数据等页面整页 401。

    if settings.tenant_auth_enabled:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="已启用租户鉴权，请登录或提供 X-API-Key")
        resolved = TenantAuthService(session, settings).resolve_tenant(x_api_key)
        if not resolved:
            raise HTTPException(status_code=403, detail="无效的 API Key")
        return resolved

    raw = (x_tenant_id or query_tenant_id or settings.default_tenant_id).strip()
    try:
        return normalize_tenant_id(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_path_tenant_id(tenant_id: str) -> str:
    try:
        return normalize_tenant_id(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def require_path_tenant(
    path_tenant_id: str,
    authenticated_tenant_id: str,
    settings: Settings,
    current_user: User | None = None,
) -> str:
    tid = resolve_path_tenant_id(path_tenant_id)
    if current_user is not None and current_user.tenant_id != tid:
        raise HTTPException(status_code=403, detail="无权访问该租户")
    if settings.tenant_auth_enabled and tid != authenticated_tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该租户")
    return tid


def effective_tenant_id(
    authenticated_tenant_id: str,
    override: str | None,
    settings: Settings,
) -> str:
    if override:
        try:
            requested = normalize_tenant_id(override)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if settings.tenant_auth_enabled and requested != authenticated_tenant_id:
            raise HTTPException(status_code=403, detail="无权代表其他租户操作")
        if not settings.tenant_auth_enabled:
            return requested
    return authenticated_tenant_id


def effective_platform_id(
    dep_platform_id: str,
    override: str | None,
) -> str:
    if override:
        try:
            return normalize_platform(override)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dep_platform_id


def verify_admin_secret(
    x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_api_secret or x_admin_secret != settings.admin_api_secret:
        raise HTTPException(status_code=403, detail="Admin Secret 无效或未配置")


def platform_session_store(
    platform: str = Depends(get_platform_id),
    settings: Settings = Depends(get_settings),
) -> PlatformSessionStore:
    return get_session_store(settings, platform)

