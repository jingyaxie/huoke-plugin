from datetime import datetime

from pydantic import BaseModel

from app.platforms.constants import DEFAULT_PLATFORM


class CrawlItem(BaseModel):
    platform: str = DEFAULT_PLATFORM
    rank: int
    title: str
    author_name: str | None = None
    external_id: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    publish_time: datetime | None = None
    author_avatar_url: str | None = None
    author_profile_url: str | None = None
    raw_data: dict | None = None


class CrawlResult(BaseModel):
    platform: str = DEFAULT_PLATFORM
    snapshot_date: str
    total: int
    items: list[CrawlItem]
