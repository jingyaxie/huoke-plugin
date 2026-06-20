from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings
from app.schemas.interaction_settings import InteractionSettings, InteractionSettingsUpdate

_DEFAULTS: dict[str, Any] = InteractionSettings().model_dump()


class InteractionSettingsService:
    def __init__(self, settings: Settings, tenant_id: str) -> None:
        self.root = settings.storage_root / "tenants" / tenant_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "interaction_settings.json"

    def read(self) -> InteractionSettings:
        if not self.path.is_file():
            return InteractionSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return InteractionSettings()
        if not isinstance(raw, dict):
            return InteractionSettings()
        merged = {**_DEFAULTS, **raw}
        return InteractionSettings.model_validate(merged)

    def save(self, patch: InteractionSettingsUpdate) -> InteractionSettings:
        current = self.read().model_dump()
        updates = patch.model_dump(exclude_unset=True)
        current.update(updates)
        next_settings = InteractionSettings.model_validate(current)
        self.path.write_text(
            json.dumps(next_settings.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return next_settings
