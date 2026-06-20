from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.platforms.search_filters import normalize_region
from app.schemas.crawl_cache import CacheMeta, CrawlCacheOptions


class XhsSearchNotesRequest(CrawlCacheOptions):
    keyword: str = Field(min_length=1, max_length=100, description="搜索关键词")
    limit: int = Field(default=10, ge=1, le=20, description="返回笔记数量上限")
    show_browser: bool = Field(default=False, description="是否使用可见浏览器（调试用）")
    days: Optional[int] = Field(default=None, ge=1, le=30, description="最近天数筛选，不传则不限制")
    region: Optional[str] = Field(default=None, description="地域筛选，不传或留空则不限制")

    @field_validator("region", mode="before")
    @classmethod
    def _normalize_region(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_region(str(value))


class XhsNoteCommentsRequest(CrawlCacheOptions):
    note_url: str = Field(description="小红书笔记链接")
    max_comments: int = Field(default=200, ge=1, le=500, description="顶层评论抓取上限")
    show_browser: bool = False


class XhsKeywordCommentsRequest(CrawlCacheOptions):
    keyword: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=3, ge=1, le=20, description="搜索笔记数量")
    max_comments: int = Field(default=200, ge=1, le=500, description="每个笔记的顶层评论上限")
    show_browser: bool = False
    days: int = Field(default=3, ge=1, le=30)
    region: Optional[str] = Field(default=None, description="地域筛选，不传或留空则不限制")

    @field_validator("region", mode="before")
    @classmethod
    def _normalize_region_kw(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_region(str(value))


class XhsUserTarget(BaseModel):
    """评论用户或任意小红书用户定位（单次仅操作一人）。"""

    user_id: str = Field(min_length=1, description="用户 user_id，用于拼主页 URL 和关注接口")
    username: Optional[str] = Field(default=None, description="昵称，仅用于报告展示")


class XhsFollowUserRequest(XhsUserTarget):
    show_browser: bool = False


class XhsUnfollowUserRequest(XhsUserTarget):
    show_browser: bool = False


class XhsSendMessageRequest(XhsUserTarget):
    message: str = Field(min_length=1, max_length=500, description="私信内容")
    show_browser: bool = False


class XhsToolResponse(BaseModel):
    ok: bool
    platform: Literal["xiaohongshu"] = "xiaohongshu"
    tenant_id: str
    account_id: str
    tool: str
    data: dict
    diagnostic: Optional[str] = None
    report_file: Optional[str] = None
    cache: CacheMeta | None = None
