from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.models.interaction_log import InteractionLog
from app.repositories.base import BaseRepository


class InteractionLogRepository(BaseRepository):
    def count_success_since(
        self,
        *,
        platform: str,
        action: str,
        since: datetime,
        account_id: str | None = None,
    ) -> int:
        stmt = (
            select(func.count(InteractionLog.id))
            .where(InteractionLog.tenant_id == self.tenant_id)
            .where(InteractionLog.platform == platform)
            .where(InteractionLog.action == action)
            .where(InteractionLog.status == "ok")
            .where(InteractionLog.created_at >= since)
        )
        if account_id:
            stmt = stmt.where(InteractionLog.account_id == account_id)
        return int(self.session.scalar(stmt) or 0)

    def has_success(
        self,
        *,
        platform: str,
        action: str,
        comment_id: str | None = None,
        target_user_id: str | None = None,
        target_sec_uid: str | None = None,
        account_id: str | None = None,
    ) -> bool:
        stmt = (
            select(func.count(InteractionLog.id))
            .where(InteractionLog.tenant_id == self.tenant_id)
            .where(InteractionLog.platform == platform)
            .where(InteractionLog.action == action)
            .where(InteractionLog.status == "ok")
        )
        if account_id:
            stmt = stmt.where(InteractionLog.account_id == account_id)
        if comment_id:
            stmt = stmt.where(InteractionLog.comment_id == comment_id)
        if target_user_id and target_sec_uid:
            stmt = stmt.where(
                (InteractionLog.target_user_id == target_user_id)
                | (InteractionLog.target_sec_uid == target_sec_uid)
            )
        elif target_user_id:
            stmt = stmt.where(InteractionLog.target_user_id == target_user_id)
        elif target_sec_uid:
            stmt = stmt.where(InteractionLog.target_sec_uid == target_sec_uid)
        return int(self.session.scalar(stmt) or 0) > 0

    def list_logs(
        self,
        *,
        platform: str,
        action: str | None = None,
        comment_id: str | None = None,
        target_user_id: str | None = None,
        since: datetime | None = None,
        account_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[InteractionLog], int]:
        base = (
            select(InteractionLog)
            .where(InteractionLog.tenant_id == self.tenant_id)
            .where(InteractionLog.platform == platform)
        )
        if action:
            base = base.where(InteractionLog.action == action)
        if comment_id:
            base = base.where(InteractionLog.comment_id == comment_id)
        if target_user_id:
            base = base.where(InteractionLog.target_user_id == target_user_id)
        if since:
            base = base.where(InteractionLog.created_at >= since)
        if account_id:
            base = base.where(InteractionLog.account_id == account_id)

        total = int(
            self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        )
        rows = list(
            self.session.scalars(
                base.order_by(InteractionLog.created_at.desc()).offset(offset).limit(limit)
            )
        )
        return rows, total

    def list_logs_by_task(
        self,
        *,
        task_id: str,
        platform: str,
        account_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[InteractionLog], int]:
        base = (
            select(InteractionLog)
            .where(InteractionLog.tenant_id == self.tenant_id)
            .where(InteractionLog.platform == platform)
            .where(InteractionLog.task_id == task_id)
        )
        if account_id:
            base = base.where(InteractionLog.account_id == account_id)

        total = int(
            self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        )
        rows = list(
            self.session.scalars(
                base.order_by(InteractionLog.created_at.desc()).offset(offset).limit(limit)
            )
        )
        return rows, total

    def add(self, record: InteractionLog) -> InteractionLog:
        self.session.add(record)
        self.session.flush()
        return record
