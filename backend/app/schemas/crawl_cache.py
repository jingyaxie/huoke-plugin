from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


DEFAULT_CACHE_TTL_HOURS = 24.0


class CrawlCacheOptions(BaseModel):
    """抓取类接口通用缓存控制参数。"""

    force_refresh: bool = Field(
        default=False,
        description="强制即时拉取，忽略缓存；若拉取失败则自动回退返回已有缓存",
    )
    cache_ttl_hours: float = Field(
        default=DEFAULT_CACHE_TTL_HOURS,
        ge=0.25,
        le=168,
        description="缓存有效期（小时），默认 24 小时",
    )


class CacheMeta(BaseModel):
    """响应中的缓存元信息。"""

    from_cache: bool = False
    cache_hit: bool = False
    cached_at: datetime | None = None
    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    incremental_merge: bool = False
    new_comments_added: int = 0
    updated_comments: int = 0
    stale_fallback: bool = False
    refresh_error: str | None = None
