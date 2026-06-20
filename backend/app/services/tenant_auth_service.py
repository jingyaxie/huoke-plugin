from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.tenant_api_key import TenantApiKey
from app.platforms.tenant import normalize_tenant_id


class TenantAuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    @staticmethod
    def hash_api_key(api_key: str, pepper: str) -> str:
        return hashlib.sha256(f"{pepper}:{api_key}".encode("utf-8")).hexdigest()

    def resolve_tenant(self, api_key: str) -> str | None:
        key_hash = self.hash_api_key(api_key, self.settings.tenant_auth_pepper)
        row = self.session.scalar(
            select(TenantApiKey.tenant_id).where(
                TenantApiKey.key_hash == key_hash,
                TenantApiKey.is_active.is_(True),
            )
        )
        return row

    def create_api_key(self, tenant_id: str, label: str = "") -> tuple[str, TenantApiKey]:
        tenant_id = normalize_tenant_id(tenant_id)
        api_key = secrets.token_urlsafe(32)
        row = TenantApiKey(
            tenant_id=tenant_id,
            key_hash=self.hash_api_key(api_key, self.settings.tenant_auth_pepper),
            label=label or tenant_id,
        )
        self.session.add(row)
        self.session.flush()
        return api_key, row

    def ensure_api_key(self, tenant_id: str, api_key: str, label: str = "") -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        key_hash = self.hash_api_key(api_key, self.settings.tenant_auth_pepper)
        exists = self.session.scalar(select(TenantApiKey.id).where(TenantApiKey.key_hash == key_hash))
        if exists:
            return
        self.session.add(
            TenantApiKey(
                tenant_id=tenant_id,
                key_hash=key_hash,
                label=label or tenant_id,
            )
        )
        self.session.flush()
