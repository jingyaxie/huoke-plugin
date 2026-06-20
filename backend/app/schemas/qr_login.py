from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

QrLoginStatus = Literal["pending", "scanned", "confirmed", "expired", "error", "cancelled"]


class QrLoginCreateRequest(BaseModel):
    refresh: bool = Field(default=True, description="若已有会话，是否刷新二维码")


class QrLoginCreateResponse(BaseModel):
    ok: bool
    platform: str
    tenant_id: str
    account_id: str
    session_id: str
    status: QrLoginStatus = "pending"
    qr_image_url: Optional[str] = None
    qr_image_base64: Optional[str] = None
    qr_scan_url: Optional[str] = Field(default=None, description="二维码编码的跳转链接，可供前端自行渲染")
    expires_at: Optional[str] = Field(default=None, description="ISO8601 过期时间")
    expires_in_seconds: Optional[int] = None
    validity_hint: str = "二维码约 3 分钟内有效，过期后请重新获取"
    poll_interval_seconds: int = 2
    diagnostic: Optional[str] = None


class QrLoginStatusResponse(BaseModel):
    ok: bool
    platform: str
    tenant_id: str
    account_id: str
    session_id: str
    status: QrLoginStatus
    expires_at: Optional[str] = None
    expires_in_seconds: Optional[int] = None
    validity_hint: Optional[str] = None
    poll_interval_seconds: int = 2
    message: Optional[str] = None
    login_ready: bool = False
    login_status: Optional[dict] = None
