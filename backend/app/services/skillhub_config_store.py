from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id


class SkillHubConfigStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _path(self, tenant_id: str) -> Path:
        tid = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / tid / "skillhub.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def load(self, tenant_id: str) -> dict:
        path = self._path(tenant_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def save(self, tenant_id: str, data: dict) -> dict:
        path = self._path(tenant_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def get_registry(self, tenant_id: str) -> str:
        data = self.load(tenant_id)
        return (data.get("registry") or self.settings.skillhub_registry).rstrip("/")

    def get_token(self, tenant_id: str) -> str | None:
        data = self.load(tenant_id)
        token = data.get("token") or self.settings.skillhub_token
        if token:
            return str(token).strip() or None
        return None

    def is_auto_install_enabled(self, tenant_id: str) -> bool:
        data = self.load(tenant_id)
        if "auto_install_enabled" in data:
            return bool(data["auto_install_enabled"])
        return self.settings.skillhub_auto_install_enabled
