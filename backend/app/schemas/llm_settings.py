from __future__ import annotations

from pydantic import BaseModel, Field


class LlmProviderSettingsOut(BaseModel):
    configured: bool = False
    api_key_masked: str | None = None
    base_url: str = ""
    model: str = ""


class LlmSettingsOut(BaseModel):
    env_file: str = ""
    deepseek: LlmProviderSettingsOut = Field(default_factory=LlmProviderSettingsOut)
    llm_configured: bool = False


class LlmSettingsUpdate(BaseModel):
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str | None = None


class LlmSettingsUpdateResult(BaseModel):
    ok: bool = True
    llm_configured: bool = False
    message: str = ""
