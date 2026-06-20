from __future__ import annotations

from pydantic import BaseModel, Field


class PageDiagnosisSettings(BaseModel):
    enabled: bool = True
    llm_enabled: bool = True
    screenshot_enabled: bool = True
    llm_timeout_seconds: int = Field(default=8, ge=1, le=120)
    rule_confidence_skip_llm: float = Field(default=0.92, ge=0.0, le=1.0)


class PageDiagnosisSettingsUpdate(BaseModel):
    enabled: bool | None = None
    llm_enabled: bool | None = None
    screenshot_enabled: bool | None = None
    llm_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    rule_confidence_skip_llm: float | None = Field(default=None, ge=0.0, le=1.0)
