from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class PlatformAccountCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    label: str = Field(..., min_length=1, max_length=120)


class PlatformAccountOut(BaseModel):
    id: str
    label: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PlatformAccountListResponse(BaseModel):
    items: list[PlatformAccountOut]
    total: int
    active_account_id: str = "default"


class PlatformBindingStatus(BaseModel):
    platform: str
    platform_label: str
    status: str
    message: str = ""
    cookie_count: int = 0
    cookie_ready: bool = False
    platform_user_id: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None


class PlatformAccountBindingsOut(BaseModel):
    account_id: str
    label: str
    platforms: list[PlatformBindingStatus]


class PlatformAccountUpdate(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)


class ConfirmPlatformBindingRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120, description="自定义展示名称，写入 Huoke 账号 label")


class PlatformBindingProfileOut(BaseModel):
    ok: bool
    tenant_id: str
    account_id: str
    platform: str
    label: str
    display_name: str
    platform_user_id: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    cookie_ready: bool = False
    login_status: dict[str, Any] = Field(default_factory=dict)


class UploadAccountStorageStateRequest(BaseModel):
    storage_state: dict[str, Any]


class ServerLoginRequest(BaseModel):
    restore: bool = False
