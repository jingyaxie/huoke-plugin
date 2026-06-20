from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProfileScope = Literal["global", "tenant"]

PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class AgentProfileBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    system_prompt: str = Field(default="", description="角色与任务说明，会注入系统提示")
    inherit_base_prompt: bool = Field(
        default=True,
        description="为 true 时注入运行时内核（BrowserRuntime + 通用约束）；为 false 时不注入内核",
    )
    inherit_workflow_prompt: bool = Field(
        default=True,
        description="为 true 时注入标准获客流程提示（keyword-comments / DB 查库等）；专用档案可设为 false",
    )
    exclude_rule_ids: list[str] = Field(
        default_factory=list,
        description="租户规则 ID 排除列表；用于与档案流程冲突的全局规则（如 douyin-platform）",
    )
    inherit_experience_prompt: bool = Field(
        default=True,
        description="为 true 时注入做梦归纳的历史经验；专用档案可关闭避免标准流程经验干扰",
    )
    skill_ids: list[str] = Field(
        default_factory=list,
        description="限制可用 Skill ID 列表；空表示不限制",
    )
    platforms: list[str] = Field(
        default_factory=list,
        description="适用平台；空表示全平台",
    )
    enabled: bool = True


class AgentProfileCreate(AgentProfileBase):
    id: str = Field(..., min_length=2, max_length=64)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if normalized == "default":
            raise ValueError("不能使用 id=default，请使用其他 ID")
        if not PROFILE_ID_PATTERN.match(normalized):
            raise ValueError("档案 ID 仅允许小写字母、数字、下划线、连字符")
        return normalized


class AgentProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    system_prompt: str | None = None
    inherit_base_prompt: bool | None = None
    inherit_workflow_prompt: bool | None = None
    exclude_rule_ids: list[str] | None = None
    inherit_experience_prompt: bool | None = None
    skill_ids: list[str] | None = None
    platforms: list[str] | None = None
    enabled: bool | None = None


class AgentProfileOut(AgentProfileBase):
    id: str
    scope: ProfileScope = "tenant"


class AgentProfileListResponse(BaseModel):
    items: list[AgentProfileOut]
    total: int
