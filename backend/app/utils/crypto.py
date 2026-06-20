from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def _fernet(key: str) -> Fernet:
    return Fernet(key.encode("utf-8"))


def encrypt_json(data: dict[str, Any], key: str) -> str:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return _fernet(key).encrypt(payload).decode("utf-8")


def decrypt_json(token: str, key: str) -> dict[str, Any]:
    try:
        raw = _fernet(key).decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("登录态解密失败，请检查 STORAGE_STATE_ENCRYPTION_KEY") from exc
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("登录态格式无效")
    return parsed
