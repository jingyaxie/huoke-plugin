from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.auth import RegisterRequest
from app.services.user_auth_service import UserAuthError, UserAuthService


def ensure_bootstrap_admin(session: Session, settings: Settings) -> bool:
    """首次部署时创建默认管理员账号（已存在则跳过）。"""
    username = (os.getenv("BOOTSTRAP_ADMIN_USERNAME") or "admin").strip()
    password = (os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or "admin123").strip()
    tenant_id = normalize_tenant_id(os.getenv("BOOTSTRAP_ADMIN_TENANT_ID") or "default")
    if not username or not password:
        return False

    auth = UserAuthService(session, settings)
    if auth.get_user_by_username(username):
        return False

    auth.provision_bridge_user(
        RegisterRequest(
            username=username,
            password=password,
            tenant_id=tenant_id,
            tenant_name="默认租户",
            display_name="管理员",
        )
    )
    return True
