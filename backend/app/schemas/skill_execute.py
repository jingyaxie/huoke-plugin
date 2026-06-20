from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SkillExecuteRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    platform: str | None = Field(default=None, description="覆盖默认平台上下文")
    account_id: str | None = None
    headless: bool | None = None
    agent_fallback: bool = Field(
        default=False,
        description="instruction 型技能或 pipeline 失败时是否启动受限 Agent 兜底",
    )
    provider: Literal["openai", "deepseek"] = "deepseek"
    timeout_seconds: int = Field(default=600, ge=60, le=3600)


class SkillExecuteResponse(BaseModel):
    ok: bool
    skill_id: str
    platform: str
    tenant_id: str
    account_id: str
    status: str
    summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    recovery_stage: str | None = None
    run_id: str | None = None
