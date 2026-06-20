from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KeywordContextOut(BaseModel):
    keyword: str | None = None
    search_keyword: str | None = None
    days: int | None = None
    region: str | None = None
    guest_mode: bool | None = None
    session_mode: str | None = None


class ContentMetaOut(BaseModel):
    platform: str
    external_id: str | None = None
    title: str | None = None
    author_name: str | None = None
    author_id: str | None = None
    cover_url: str | None = None
    content_url: str | None = None
    video_url: str | None = None
    note_url: str | None = None
    like_count: int | None = None
    share_count: int | None = None
    publish_time: int | None = None
    capture_method: str | None = None
    api_total_top_comments: int | None = None
    keyword_context: KeywordContextOut | None = None
    warning: str | None = None
    guest_mode: bool | None = None
    session_mode: str | None = None
    file_modified_at: datetime | None = None
    extra: dict[str, Any] | None = None


class ContentSummaryOut(BaseModel):
    content_id: str
    platform: str
    tenant_id: str | None = None
    content_url: str | None = None
    comment_count: int = 0
    top_comment_count: int = 0
    last_seen_at: datetime | None = None
    updated_at: datetime | None = None
    canonical_file: str | None = None
    meta: ContentMetaOut | None = None


class ContentListResponse(BaseModel):
    platform: str
    tenant_id: str
    total: int
    items: list[ContentSummaryOut]


class CommentUserOut(BaseModel):
    user_id: str | None = None
    sec_uid: str | None = None
    username: str = ""
    avatar: str | None = None


class CommentItemOut(BaseModel):
    comment_id: str
    parent_comment_id: str | None = None
    comment: str = ""
    nickname: str = ""
    digg_count: int = 0
    create_time: int | None = None
    reply_comment_total: int = 0
    photo_author_id: str | None = None
    user: CommentUserOut


class ContentDetailOut(BaseModel):
    platform: str
    tenant_id: str
    content_id: str
    content_url: str | None = None
    video_url: str | None = None
    note_url: str | None = None
    total_comments_captured: int = 0
    top_comments_captured: int = 0
    capture_method: str | None = None
    canonical_file: str | None = None
    comments: list[CommentItemOut] = Field(default_factory=list)
    storage_meta: dict[str, Any] | None = None
    meta: ContentMetaOut | None = None
