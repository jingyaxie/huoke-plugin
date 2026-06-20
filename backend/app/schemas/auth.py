from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=128)
    email: str | None = Field(default=None, max_length=128)
    tenant_id: str | None = Field(default=None, max_length=64)
    tenant_name: str | None = Field(default=None, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("用户名仅允许字母、数字、下划线、连字符")
        return value


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class BridgeAuthRequest(BaseModel):
    """外部系统（如 AI销售）向 Huoke 同步登录/开户。"""

    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    tenant_id: str = Field(..., min_length=1, max_length=64)
    tenant_name: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("用户名仅允许字母、数字、下划线、连字符")
        return value


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None = None
    tenant_id: str
    role: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantOut(BaseModel):
    id: str
    name: str
    owner_user_id: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    tenant: TenantOut


class UserListResponse(BaseModel):
    items: list[UserOut]
    total: int


class TenantListResponse(BaseModel):
    items: list[TenantOut]
    total: int
