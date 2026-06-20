from __future__ import annotations

import time
from datetime import datetime, timezone


def utc_iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def expires_in_seconds(expires_at: float | int | None) -> int | None:
    if expires_at is None:
        return None
    return max(0, int(float(expires_at) - time.time()))


def normalize_image_base64(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("data:image"):
        return text
    return f"data:image/png;base64,{text}"


def douyin_status_from_check(data: dict) -> tuple[str, str | None]:
    payload = data.get("data") if isinstance(data, dict) else {}
    if not isinstance(payload, dict):
        return "error", "二维码状态响应异常"
    if payload.get("error_code") not in (None, 0):
        return "error", payload.get("description") or payload.get("desc_url") or "获取二维码状态失败"
    status = str(payload.get("status") or "").lower()
    mapping = {
        "new": ("pending", "请使用抖音 App 扫码"),
        "scanned": ("scanned", "已扫码，请在手机上确认登录"),
        "confirmed": ("confirmed", "登录成功"),
        "expired": ("expired", "二维码已过期，请重新获取"),
        "refused": ("error", "用户拒绝登录"),
    }
    if status in mapping:
        return mapping[status]
    return "pending", payload.get("description") or None


def kuaishou_status_from_scan(data: dict) -> tuple[str, str | None]:
    if not isinstance(data, dict):
        return "error", "二维码状态响应异常"
    result = data.get("result")
    if result == 1 and isinstance(data.get("user"), dict):
        return "scanned", "已扫码，请在手机上确认登录"
    if result in {707, 100110031}:
        return "expired", data.get("error_msg") or "二维码已过期，请重新获取"
    if result not in (None, 0) and data.get("error_msg"):
        return "error", str(data.get("error_msg"))
    return "pending", "请使用快手 App 扫码"


def xhs_status_from_poll(data: dict) -> tuple[str, str | None]:
    if not isinstance(data, dict):
        return "error", "二维码状态响应异常"
    if data.get("code") not in (0, None) and not data.get("success"):
        return "error", data.get("msg") or "获取二维码状态失败"
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    code_status = payload.get("code_status")
    if code_status == 2:
        return "confirmed", "登录成功"
    if code_status == 1:
        return "scanned", "已扫码，请在手机上确认登录"
    if code_status in {3, 4}:
        return "expired", "二维码已过期，请重新获取"
    return "pending", "请使用小红书 App 扫码"
