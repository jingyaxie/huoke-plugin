from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PresetKind = Literal["comments", "dm-openers"]


class PresetTemplate(BaseModel):
    id: str
    name: str
    content: str
    created_at: str | None = None
    updated_at: str | None = None


class PresetListOut(BaseModel):
    items: list[PresetTemplate] = Field(default_factory=list)
    total: int = 0


class PresetCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=4000)


class PresetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    content: str | None = Field(default=None, min_length=1, max_length=4000)
