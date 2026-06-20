from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.page_diagnosis_settings import PageDiagnosisSettings, PageDiagnosisSettingsUpdate

_DEFAULTS: dict[str, Any] = PageDiagnosisSettings().model_dump()

_RUNTIME_FIELD_MAP: dict[str, str] = {
    "enabled": "page_diagnosis_enabled",
    "llm_enabled": "page_diagnosis_llm_enabled",
    "screenshot_enabled": "page_diagnosis_screenshot_enabled",
    "llm_timeout_seconds": "page_diagnosis_llm_timeout_seconds",
    "rule_confidence_skip_llm": "page_diagnosis_rule_confidence_skip_llm",
}


class PageDiagnosisSettingsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root / "settings"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "page_diagnosis.json"

    def read(self) -> PageDiagnosisSettings:
        if not self.path.is_file():
            return PageDiagnosisSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return PageDiagnosisSettings()
        if not isinstance(raw, dict):
            return PageDiagnosisSettings()
        merged = {**_DEFAULTS, **raw}
        return PageDiagnosisSettings.model_validate(merged)

    def save(self, patch: PageDiagnosisSettingsUpdate) -> PageDiagnosisSettings:
        current = self.read().model_dump()
        updates = patch.model_dump(exclude_unset=True)
        current.update(updates)
        next_settings = PageDiagnosisSettings.model_validate(current)
        self.path.write_text(
            json.dumps(next_settings.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        apply_page_diagnosis_settings_to_runtime(self.settings, next_settings)
        patch_cached_page_diagnosis_settings(self.settings)
        return next_settings


def apply_page_diagnosis_settings_to_runtime(
    settings: Settings,
    stored: PageDiagnosisSettings,
) -> None:
    payload = stored.model_dump()
    for key, field in _RUNTIME_FIELD_MAP.items():
        setattr(settings, field, payload[key])


def bootstrap_page_diagnosis_settings(settings: Settings) -> None:
    """从 storage/settings/page_diagnosis.json 加载；忽略环境变量。"""
    stored = PageDiagnosisSettingsService(settings).read()
    apply_page_diagnosis_settings_to_runtime(settings, stored)


def patch_cached_page_diagnosis_settings(settings: Settings) -> None:
    cached = get_settings()
    if cached is settings:
        return
    for field in _RUNTIME_FIELD_MAP.values():
        setattr(cached, field, getattr(settings, field))
