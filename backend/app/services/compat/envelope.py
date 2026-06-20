"""TikHub-compatible response envelope for V3 compat routes."""
from __future__ import annotations

import uuid
from typing import Any


class CompatError(Exception):
    def __init__(self, message: str, *, code: int = 400, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail


def wrap(data: Any, *, message_zh: str = "成功", code: int = 200) -> dict[str, Any]:
    return {
        "code": code,
        "data": data,
        "message_zh": message_zh,
        "request_id": uuid.uuid4().hex,
    }


def wrap_error(exc: CompatError | Exception, *, code: int = 500) -> dict[str, Any]:
    if isinstance(exc, CompatError):
        return wrap(
            exc.detail if exc.detail is not None else {"error": exc.message},
            message_zh=exc.message,
            code=exc.code,
        )
    return wrap({"error": str(exc)}, message_zh=str(exc), code=code)
