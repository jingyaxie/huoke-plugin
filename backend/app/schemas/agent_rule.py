from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RuleScope = Literal["global", "tenant"]
AgentMode = Literal["agent", "plan", "ask"]
RunMode = Literal["auto", "confirm"]

RULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class AgentRuleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    content: str = Field(..., min_length=1)
    always_apply: bool = True
    platforms: list[str] = Field(default_factory=list)
    enabled: bool = True


class AgentRuleCreate(AgentRuleBase):
    id: str = Field(..., min_length=2, max_length=64)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not RULE_ID_PATTERN.match(normalized):
            raise ValueError("规则 ID 仅允许小写字母、数字、下划线、连字符")
        return normalized


class AgentRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    content: str | None = Field(default=None, min_length=1)
    always_apply: bool | None = None
    platforms: list[str] | None = None
    enabled: bool | None = None


class AgentRuleOut(AgentRuleBase):
    id: str
    scope: RuleScope = "tenant"


class AgentRuleListResponse(BaseModel):
    items: list[AgentRuleOut]
    total: int
