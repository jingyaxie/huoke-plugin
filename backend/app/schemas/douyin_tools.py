from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.platforms.search_filters import normalize_region
from app.schemas.crawl_cache import CacheMeta, CrawlCacheOptions


class DouyinSearchVideosRequest(CrawlCacheOptions):
    keyword: str = Field(min_length=1, max_length=100, description="搜索关键词")
    limit: int = Field(default=10, ge=1, le=20, description="返回视频数量上限")
    show_browser: bool = Field(default=False, description="是否使用可见浏览器（调试用）")
    days: Optional[int] = Field(default=None, ge=1, le=30, description="最近天数筛选，不传则不限制")
    region: Optional[str] = Field(default=None, description="地域筛选，不传或留空则不限制")

    @field_validator("region", mode="before")
    @classmethod
    def _normalize_region(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_region(str(value))


class DouyinProfileVideosRequest(CrawlCacheOptions):
    profile_url: str = Field(min_length=10, description="抖音用户主页或带 vid 的链接")
    limit: int = Field(default=10, ge=1, le=30, description="返回视频数量上限")
    show_browser: bool = Field(default=False, description="是否使用可见浏览器（调试用）")
    days: Optional[int] = Field(default=None, ge=1, le=30, description="视频发布时间筛选（天）")
    video_publish_days: Optional[int] = Field(default=None, ge=1, le=30, description="同 days")


class DouyinVideoCommentsRequest(CrawlCacheOptions):
    video_url: str = Field(description="抖音视频链接，如 https://www.douyin.com/video/{aweme_id}")
    max_comments: int = Field(default=200, ge=1, le=500, description="顶层评论抓取上限")
    show_browser: bool = False


class DouyinKeywordCommentsRequest(CrawlCacheOptions):
    keyword: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=3, ge=1, le=20, description="搜索视频数量")
    max_comments: int = Field(default=200, ge=1, le=500, description="每个视频的顶层评论上限")
    show_browser: bool = False
    guest_mode: bool = Field(
        default=False,
        description="游客态：跳过登录检查（仅搜索+评论读取，不支持关注/私信）",
    )
    days: int = Field(default=3, ge=1, le=30)
    region: Optional[str] = Field(default=None, description="地域筛选，不传或留空则不限制")

    @field_validator("region", mode="before")
    @classmethod
    def _normalize_region(cls, value: object) -> str | None:
        if value is None:
            return None
        return normalize_region(str(value))


class DouyinUserTarget(BaseModel):
    """评论用户或任意抖音用户定位（单次仅操作一人）。"""

    sec_uid: str = Field(min_length=10, description="用户 sec_uid，用于拼主页 URL")
    user_id: str = Field(min_length=1, description="数字 uid，关注接口必填")
    username: Optional[str] = Field(default=None, description="昵称，仅用于报告展示")


class DouyinFollowUserRequest(DouyinUserTarget):
    show_browser: bool = False


class DouyinUnfollowUserRequest(DouyinUserTarget):
    show_browser: bool = False


class DouyinSendMessageRequest(DouyinUserTarget):
    message: str = Field(min_length=1, max_length=500, description="私信内容")
    show_browser: bool = False


class DouyinVideoSummary(BaseModel):
    aweme_id: str
    video_url: str
    title: str = ""
    author: str = ""
    digg_count: int = 0
    comment_count: int = 0


class DouyinSearchVideosData(BaseModel):
    keyword: str
    video_count: int
    capture_method: str
    videos: list[DouyinVideoSummary]


class DouyinVideoCommentsData(BaseModel):
    aweme_id: str
    video_url: str
    total_comments_captured: int
    api_total_top_comments: int
    capture_method: str
    comments: list[dict] = Field(default_factory=list, description="完整评论列表（可选截断预览）")


class DouyinKeywordCommentsItem(BaseModel):
    aweme_id: str
    video_url: str
    total_comments_captured: int
    api_total_top_comments: int
    report_file: str


class DouyinKeywordCommentsData(BaseModel):
    keyword: str
    videos_found: int
    items: list[DouyinKeywordCommentsItem]
    guest_mode: bool = False
    session_mode: Literal["guest", "logged_in", "anonymous"] = "logged_in"


class DouyinFollowResult(BaseModel):
    ok: bool
    skipped: bool = False
    reason: Optional[str] = None
    follow_status_before: int = 0
    follow_status_after: int = 0
    status_msg: str = ""


class DouyinMessageResult(BaseModel):
    ok: bool
    method: str = "profile_dm_panel"
    verified_in_page: bool = False
    error: Optional[str] = None
    hint: Optional[str] = None


class DouyinStandaloneKeywordBrowseRequest(BaseModel):
    """独立关键词浏览（复用桌面稳定浏览器基座）。"""

    keyword: str = Field(min_length=1, max_length=100)
    days: int = Field(default=7, ge=1, le=30)
    limit: int = Field(default=3, ge=1, le=50, description="兼容字段；优先用 target_precise_leads")
    target_precise_leads: int = Field(default=3, ge=1, le=20, description="目标精准线索条数")
    max_videos_to_browse: int = Field(default=50, ge=1, le=100)
    comment_days: Optional[int] = Field(default=None, ge=1, le=30)
    match_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    execute_outreach: bool = False
    test_all_outreach: bool = False
    reply_text: str = ""
    dm_text: str = ""
    comment_ratio: int = Field(default=50, ge=0, le=100)
    dm_ratio: int = Field(default=30, ge=0, le=100)
    follow_ratio: int = Field(default=20, ge=0, le=100)
    persist_to_db: bool = False
    close_browser_after: bool = False


class DouyinStandaloneManualBrowseBase(BaseModel):
    """手动获客 standalone 浏览（单视频 / 主页）共用字段。"""

    input_url: str = Field(default="", description="视频或主页链接（可与下方专用字段二选一）")
    days: int = Field(default=7, ge=1, le=30, description="视频发布时间筛选（主页模式）")
    video_publish_days: Optional[int] = Field(default=None, ge=1, le=30)
    limit: int = Field(default=3, ge=1, le=50, description="兼容字段；优先用 target_precise_leads")
    target_precise_leads: int = Field(default=3, ge=1, le=20)
    max_videos_to_browse: int = Field(default=20, ge=1, le=100)
    comment_days: Optional[int] = Field(default=None, ge=1, le=30)
    match_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    execute_outreach: bool = False
    test_all_outreach: bool = False
    reply_text: str = ""
    dm_text: str = ""
    comment_ratio: int = Field(default=50, ge=0, le=100)
    dm_ratio: int = Field(default=30, ge=0, le=100)
    follow_ratio: int = Field(default=20, ge=0, le=100)
    persist_to_db: bool = False
    close_browser_after: bool = False


class DouyinStandaloneVideoBrowseRequest(DouyinStandaloneManualBrowseBase):
    video_url: str = Field(default="", description="抖音单条视频链接")


class DouyinStandaloneProfileBrowseRequest(DouyinStandaloneManualBrowseBase):
    profile_url: str = Field(default="", description="抖音用户主页链接")
    max_videos_to_browse: int = Field(default=10, ge=1, le=30, description="主页最多浏览视频数")


class DouyinToolResponse(BaseModel):
    """统一响应信封：业务数据放 data，诊断信息放 diagnostic。"""

    ok: bool
    platform: Literal["douyin"] = "douyin"
    tenant_id: str
    account_id: str
    tool: str
    data: dict
    diagnostic: Optional[str] = None
    report_file: Optional[str] = None
    cache: CacheMeta | None = None
