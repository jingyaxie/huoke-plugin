import re

_TENANT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def normalize_tenant_id(tenant_id: str) -> str:
    value = (tenant_id or "").strip()
    if not value or not _TENANT_ID_PATTERN.fullmatch(value):
        raise ValueError("tenant_id 仅允许字母、数字、点、下划线、连字符，且长度 1-64")
    return value
