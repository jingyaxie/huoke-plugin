from __future__ import annotations

from pydantic import BaseModel, Field


class InteractionSettings(BaseModel):
    comment_dm_interval_seconds_min: int = Field(default=10, ge=1, le=600)
    comment_dm_interval_seconds_max: int = Field(default=30, ge=1, le=600)
    comment_dm_percentage: int = Field(default=50, ge=0, le=100)
    follow_per_day: int = Field(default=30, ge=0, le=1000)
    dm_per_day: int = Field(default=30, ge=0, le=1000)
    batch_cooldown_minutes: int = Field(default=8, ge=0, le=120)
    strategy_id: str | None = None


class InteractionSettingsUpdate(BaseModel):
    comment_dm_interval_seconds_min: int | None = Field(default=None, ge=1, le=600)
    comment_dm_interval_seconds_max: int | None = Field(default=None, ge=1, le=600)
    comment_dm_percentage: int | None = Field(default=None, ge=0, le=100)
    follow_per_day: int | None = Field(default=None, ge=0, le=1000)
    dm_per_day: int | None = Field(default=None, ge=0, le=1000)
    batch_cooldown_minutes: int | None = Field(default=None, ge=0, le=120)
    strategy_id: str | None = None
