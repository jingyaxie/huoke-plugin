from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InteractionLog(Base):
    """互动动作台账：回复/关注/私信等，用于配额统计与去重。"""

    __tablename__ = "interaction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")

    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    engine: Mapped[str] = mapped_column(String(64), nullable=False, default="agent_skill")

    comment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    content_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    target_sec_uid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_nickname: Mapped[str | None] = mapped_column(String(255), nullable=True)

    keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
