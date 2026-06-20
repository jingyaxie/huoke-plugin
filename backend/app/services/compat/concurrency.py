from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.core.config import Settings

_semaphore: asyncio.Semaphore | None = None
_semaphore_limit: int = 0


def _ensure_semaphore(settings: Settings) -> asyncio.Semaphore:
    global _semaphore, _semaphore_limit
    limit = max(1, int(getattr(settings, "compat_max_concurrent", 3) or 3))
    if _semaphore is None or _semaphore_limit != limit:
        _semaphore = asyncio.Semaphore(limit)
        _semaphore_limit = limit
    return _semaphore


@asynccontextmanager
async def compat_slot(settings: Settings) -> AsyncIterator[None]:
    sem = _ensure_semaphore(settings)
    async with sem:
        yield
