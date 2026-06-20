from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.platforms.search_filters import normalize_region
from app.schemas.crawl_cache import CacheMeta, CrawlCacheOptions


PipelinePlatform = Literal["douyin", "xiaohongshu"]


class KeywordVideoCommentsRequest(CrawlCacheOptions):
    keyword: str = Field(..., min_length=1, max_length=200)
    platforms: list[PipelinePlatform] = Field(
        default_factory=lambda: ["douyin", "xiaohongshu"]
    )
    video_limit: int = Field(default=5, ge=1, le=20)
    days: int = Field(default=3, ge=1, le=30, description="评论采集天数（comment_days）")
    video_publish_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description="视频发布时间筛选；不传则与 days 相同",
    )
    region: Optional[str] = Field(default=None, description="地域筛选，如 辽宁 / 沈阳；不传则不限制")
    account_id: str | None = None
    provider: Literal["openai", "deepseek"] = "deepseek"
    headless: bool | None = None
    timeout_seconds: int = Field(default=1200, ge=60, le=3600)
    async_job: bool = Field(default=False, description="为 true 时提交异步任务并返回 job_id")

    @field_validator("region", mode="before")
    @classmethod
    def _normalize_region(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_region(str(value))


class PlatformPipelineResult(BaseModel):
    platform: str
    status: str
    run_id: str | None = None
    summary: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class KeywordVideoCommentsResponse(BaseModel):
    keyword: str
    status: str
    platforms: list[PlatformPipelineResult] = Field(default_factory=list)
    job_id: str | None = None
    completed_at: datetime | None = None
    cache: CacheMeta | None = None
