from __future__ import annotations

import re

_ACCOUNT_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def normalize_account_id(account_id: str | None) -> str:
    value = (account_id or "default").strip()
    if not value:
        return "default"
    if not _ACCOUNT_PATTERN.fullmatch(value):
        raise ValueError("account_id 仅允许字母数字、下划线、连字符，长度 1-64")
    return value
