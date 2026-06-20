from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.tenant import Tenant
from app.models.user import User
from app.platforms.tenant import normalize_tenant_id
from app.schemas.auth import RegisterRequest, TenantOut, UserOut


class UserAuthError(ValueError):
    pass


class UserAuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    @staticmethod
    def hash_password(password: str, pepper: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            f"{pepper}:{password}".encode("utf-8"),
            salt.encode("utf-8"),
            260_000,
        )
        return f"pbkdf2_sha256${salt}${digest.hex()}"

    @staticmethod
    def verify_password(password: str, pepper: str, stored: str) -> bool:
        try:
            algo, salt, digest_hex = stored.split("$", 2)
        except ValueError:
            return False
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            f"{pepper}:{password}".encode("utf-8"),
            salt.encode("utf-8"),
            260_000,
        )
        return secrets.compare_digest(digest.hex(), digest_hex)

    def create_access_token(self, user: User) -> tuple[str, int]:
        expires_minutes = max(int(self.settings.jwt_expire_minutes), 5)
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.id),
            "username": user.username,
            "tenant_id": user.tenant_id,
            "role": user.role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        }
        token = jwt.encode(payload, self.settings.jwt_secret, algorithm="HS256")
        return token, expires_minutes * 60

    def decode_access_token(self, token: str) -> dict:
        try:
            return jwt.decode(token, self.settings.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise UserAuthError("无效或已过期的登录令牌") from exc

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_user_by_username(self, username: str) -> User | None:
        return self.session.scalar(select(User).where(User.username == username.strip()))

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self.session.get(Tenant, tenant_id)

    def register(self, payload: RegisterRequest) -> tuple[User, Tenant]:
        username = payload.username.strip()
        if self.get_user_by_username(username):
            raise UserAuthError("用户名已存在")

        tenant_id = normalize_tenant_id(payload.tenant_id or username)
        if self.get_tenant(tenant_id):
            raise UserAuthError(f"租户 ID「{tenant_id}」已存在，请更换 tenant_id 或直接登录")

        now = datetime.utcnow()
        tenant = Tenant(
            id=tenant_id,
            name=(payload.tenant_name or payload.display_name or username).strip() or tenant_id,
            owner_user_id=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        user = User(
            username=username,
            email=(payload.email or "").strip() or None,
            password_hash=self.hash_password(payload.password, self.settings.user_auth_pepper),
            tenant_id=tenant_id,
            role="owner",
            display_name=(payload.display_name or username).strip(),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(tenant)
        self.session.add(user)
        self.session.flush()
        tenant.owner_user_id = user.id
        self.session.flush()
        return user, tenant

    def provision_bridge_user(self, payload: RegisterRequest) -> tuple[User, Tenant]:
        """为外部系统联动开户：租户已存在时追加成员，否则创建租户+owner。"""
        username = payload.username.strip()
        tenant_id = normalize_tenant_id(payload.tenant_id or username)
        password_hash = self.hash_password(payload.password, self.settings.user_auth_pepper)
        now = datetime.utcnow()

        existing_user = self.get_user_by_username(username)
        tenant = self.get_tenant(tenant_id)

        if existing_user is not None:
            if existing_user.tenant_id != tenant_id:
                raise UserAuthError("用户名已绑定其他租户")
            existing_user.password_hash = password_hash
            existing_user.display_name = (payload.display_name or existing_user.display_name or username).strip()
            existing_user.is_active = True
            existing_user.updated_at = now
            if tenant is None:
                raise UserAuthError("所属租户不存在")
            if not tenant.is_active:
                raise UserAuthError("所属租户不可用")
            self.session.flush()
            return existing_user, tenant

        if tenant is not None:
            if not tenant.is_active:
                raise UserAuthError("所属租户不可用")
            user = User(
                username=username,
                email=(payload.email or "").strip() or None,
                password_hash=password_hash,
                tenant_id=tenant_id,
                role="member",
                display_name=(payload.display_name or username).strip(),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            self.session.add(user)
            self.session.flush()
            return user, tenant

        tenant = Tenant(
            id=tenant_id,
            name=(payload.tenant_name or payload.display_name or username).strip() or tenant_id,
            owner_user_id=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        user = User(
            username=username,
            email=(payload.email or "").strip() or None,
            password_hash=password_hash,
            tenant_id=tenant_id,
            role="owner",
            display_name=(payload.display_name or username).strip(),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(tenant)
        self.session.add(user)
        self.session.flush()
        tenant.owner_user_id = user.id
        self.session.flush()
        return user, tenant

    def login(self, username: str, password: str) -> User:
        user = self.get_user_by_username(username.strip())
        if user is None or not user.is_active:
            raise UserAuthError("用户名或密码错误")
        if not self.verify_password(password, self.settings.user_auth_pepper, user.password_hash):
            raise UserAuthError("用户名或密码错误")
        tenant = self.get_tenant(user.tenant_id)
        if tenant is None or not tenant.is_active:
            raise UserAuthError("所属租户不可用")
        return user

    def list_users_in_tenant(self, tenant_id: str) -> list[User]:
        return list(
            self.session.scalars(
                select(User).where(User.tenant_id == tenant_id).order_by(User.id.asc())
            )
        )

    @staticmethod
    def to_user_out(user: User) -> UserOut:
        return UserOut.model_validate(user)

    @staticmethod
    def to_tenant_out(tenant: Tenant) -> TenantOut:
        return TenantOut.model_validate(tenant)
