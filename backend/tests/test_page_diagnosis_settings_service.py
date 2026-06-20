from __future__ import annotations

import tempfile
from pathlib import Path

from app.core.config import Settings
from app.schemas.page_diagnosis_settings import PageDiagnosisSettingsUpdate
from app.services.page_diagnosis_settings_service import (
    PageDiagnosisSettingsService,
    bootstrap_page_diagnosis_settings,
)


def test_page_diagnosis_settings_defaults_and_patch():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(storage_root=Path(tmp))
        svc = PageDiagnosisSettingsService(settings)
        initial = svc.read()
        assert initial.enabled is True
        assert initial.llm_enabled is True
        assert initial.llm_timeout_seconds == 8

        saved = svc.save(
            PageDiagnosisSettingsUpdate(
                enabled=False,
                llm_timeout_seconds=15,
                rule_confidence_skip_llm=0.95,
            )
        )
        assert saved.enabled is False
        assert saved.llm_timeout_seconds == 15
        assert saved.rule_confidence_skip_llm == 0.95
        assert saved.screenshot_enabled is True

        reloaded = svc.read()
        assert reloaded.enabled is False
        assert reloaded.llm_timeout_seconds == 15


def test_bootstrap_page_diagnosis_settings_overrides_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("PAGE_DIAGNOSIS_ENABLED", "0")
        settings = Settings(storage_root=Path(tmp))
        svc = PageDiagnosisSettingsService(settings)
        svc.save(PageDiagnosisSettingsUpdate(enabled=True, llm_enabled=False))

        fresh = Settings(storage_root=Path(tmp))
        bootstrap_page_diagnosis_settings(fresh)
        assert fresh.page_diagnosis_enabled is True
        assert fresh.page_diagnosis_llm_enabled is False
