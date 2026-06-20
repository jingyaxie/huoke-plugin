from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.antibot import TenantAntibotOverrideOut


class TenantAntibotStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root / "tenants"
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, tenant_id: str) -> Path:
        safe = normalize_tenant_id(tenant_id)
        return self.root / safe / "antibot.json"

    def load(self, tenant_id: str) -> TenantAntibotOverrideOut | None:
        path = self.path_for(tenant_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("antibot.json 格式无效")
        return TenantAntibotOverrideOut.model_validate(raw)

    def save(self, tenant_id: str, override: TenantAntibotOverrideOut) -> Path:
        path = self.path_for(tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = override.model_dump(exclude_none=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def delete(self, tenant_id: str) -> bool:
        path = self.path_for(tenant_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def load_safe(self, tenant_id: str) -> TenantAntibotOverrideOut | None:
        try:
            return self.load(tenant_id)
        except (json.JSONDecodeError, ValidationError, ValueError):
            return None
