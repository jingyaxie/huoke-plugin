from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ExperienceOutcome = Literal["success", "failure", "partial"]
ExperienceScope = Literal["tenant"]

EXPERIENCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class AgentExperienceBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    task_keywords: list[str] = Field(default_factory=list)
    outcome: ExperienceOutcome = "partial"
    lesson: str = Field(..., min_length=1)
    do_tips: list[str] = Field(default_factory=list)
    avoid_tips: list[str] = Field(default_factory=list)
    platform: str = ""
    agent_profile_id: str = Field(
        default="",
        description="来源 Agent 档案 ID；空表示全局经验，任意档案可引用",
    )
    source_run_id: str | None = None
    enabled: bool = True
    version: int = 1
    supersedes_id: str | None = None
    conflict_tag: str = ""


class AgentExperienceCreate(AgentExperienceBase):
    id: str = Field(..., min_length=2, max_length=64)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not EXPERIENCE_ID_PATTERN.match(normalized):
            raise ValueError("经验 ID 仅允许小写字母、数字、下划线、连字符")
        return normalized


class AgentExperienceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    task_keywords: list[str] | None = None
    outcome: ExperienceOutcome | None = None
    lesson: str | None = Field(default=None, min_length=1)
    do_tips: list[str] | None = None
    avoid_tips: list[str] | None = None
    enabled: bool | None = None


class AgentExperienceOut(AgentExperienceBase):
    id: str
    scope: ExperienceScope = "tenant"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentExperienceListResponse(BaseModel):
    items: list[AgentExperienceOut]
    total: int


class AgentDreamResult(BaseModel):
    created: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AgentDreamRunRequest(BaseModel):
    use_llm: bool = False
