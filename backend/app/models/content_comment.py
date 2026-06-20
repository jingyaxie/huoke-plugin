from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContentComment(Base):
    """内容评论增量存储：按 comment_id 去重，支持跨次抓取合并。"""

    __tablename__ = "content_comments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "platform",
            "content_id",
            "comment_id",
            name="uq_content_comments",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    comment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_comment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    nickname: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    digg_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    create_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
