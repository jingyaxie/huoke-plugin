from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.platforms.search_filters import normalize_region
from app.schemas.crawl_cache import CacheMeta, CrawlCacheOptions


class VideoCommentCrawlRequest(CrawlCacheOptions):
    video_url: str
    show_browser: bool = False
    tenant_id: Optional[str] = None
    platform: Optional[str] = None


class DouyinLoginRequest(BaseModel):
    show_browser: bool = True
    tenant_id: Optional[str] = None
    platform: Optional[str] = None


class KeywordCommentCrawlRequest(CrawlCacheOptions):
    keyword: str
    limit: int = Field(default=3, ge=1, le=20)
    show_browser: bool = False
    guest_mode: bool = Field(
        default=False,
        description="游客态：跳过登录检查，使用抖音自动下发的会话 Cookie（仅抖音）",
    )
    days: int = Field(default=3, ge=1, le=30)
    region: Optional[str] = Field(default=None, description="地域筛选，不传或留空则不限制")
    tenant_id: Optional[str] = None

    @field_validator("region", mode="before")
    @classmethod
    def _normalize_region(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_region(str(value))
    platform: Optional[str] = None


class UploadStorageStateRequest(BaseModel):
    storage_state: dict[str, Any]


class CommentCrawlResult(BaseModel):
    video_url: str
    output_file: str
    total_comments_captured: int
    api_total_top_comments: int
    cache: CacheMeta | None = None


class KeywordCommentCrawlResponse(BaseModel):
    keyword: str
    videos_found: int
    crawled: int
    diagnostic: str | None = None
    guest_mode: bool = False
    session_mode: Literal["guest", "logged_in", "anonymous"] = "logged_in"
    items: list[CommentCrawlResult]
    cache: CacheMeta | None = None
