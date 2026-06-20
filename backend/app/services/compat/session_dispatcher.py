from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.platforms.registry import get_session_store
from app.platforms.session_store import PlatformSessionStore


@dataclass(frozen=True)
class CompatSession:
    tenant_id: str
    account_id: str
    platform: str
    store: PlatformSessionStore

    @property
    def storage_state(self) -> dict | None:
        try:
            return self.store.load(self.tenant_id, self.account_id)
        except Exception:
            return None

    def login_status(self) -> dict:
        return self.store.login_status(self.tenant_id, self.account_id)


def load_session(settings: Settings, *, tenant_id: str, account_id: str, platform: str) -> CompatSession:
    store = get_session_store(settings, platform)
    return CompatSession(
        tenant_id=tenant_id,
        account_id=account_id,
        platform=platform,
        store=store,
    )
