from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select

from app.models.content_comment import ContentComment
from app.repositories.base import BaseRepository


class ContentSummaryRow:
    def __init__(
        self,
        *,
        content_id: str,
        content_url: str | None,
        comment_count: int,
        top_comment_count: int,
        last_seen_at,
    ) -> None:
        self.content_id = content_id
        self.content_url = content_url
        self.comment_count = comment_count
        self.top_comment_count = top_comment_count
        self.last_seen_at = last_seen_at


class ContentCommentRepository(BaseRepository):
    def list_content_summaries(
        self,
        *,
        platform: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ContentSummaryRow], int]:
        total = int(
            self.session.scalar(
                select(func.count(func.distinct(ContentComment.content_id)))
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
            )
            or 0
        )
        rows = self.session.execute(
            select(
                ContentComment.content_id,
                func.max(ContentComment.content_url).label("content_url"),
                func.count(ContentComment.id).label("comment_count"),
                func.sum(
                    case((ContentComment.parent_comment_id.is_(None), 1), else_=0)
                ).label("top_comment_count"),
                func.max(ContentComment.last_seen_at).label("last_seen_at"),
            )
            .where(ContentComment.tenant_id == self.tenant_id)
            .where(ContentComment.platform == platform)
            .group_by(ContentComment.content_id)
            .order_by(func.max(ContentComment.last_seen_at).desc())
            .offset(offset)
            .limit(limit)
        ).all()
        items = [
            ContentSummaryRow(
                content_id=row.content_id,
                content_url=row.content_url,
                comment_count=int(row.comment_count or 0),
                top_comment_count=int(row.top_comment_count or 0),
                last_seen_at=row.last_seen_at,
            )
            for row in rows
        ]
        return items, total

    def list_all_content_summaries(self, *, platform: str) -> list[ContentSummaryRow]:
        items, _ = self.list_content_summaries(platform=platform, offset=0, limit=1_000_000)
        return items

    def list_by_content(self, *, platform: str, content_id: str) -> list[ContentComment]:
        return list(
            self.session.scalars(
                select(ContentComment)
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
                .where(ContentComment.content_id == content_id)
                .order_by(
                    ContentComment.create_time.is_(None),
                    ContentComment.create_time.desc(),
                    ContentComment.id.desc(),
                )
            ).all()
        )

    def list_by_content_ids(
        self,
        *,
        platform: str,
        content_ids: list[str],
        limit: int = 5000,
    ) -> list[ContentComment]:
        ids = [str(item).strip() for item in content_ids if str(item).strip()]
        if not ids:
            return []
        unique_ids = list(dict.fromkeys(ids))[:200]
        return list(
            self.session.scalars(
                select(ContentComment)
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
                .where(ContentComment.content_id.in_(unique_ids))
                .order_by(ContentComment.last_seen_at.desc(), ContentComment.id.desc())
                .limit(max(min(limit, 5000), 1))
            ).all()
        )

    def list_by_comment_ids(
        self,
        *,
        platform: str,
        comment_ids: list[str],
        limit: int = 500,
    ) -> list[ContentComment]:
        ids = [str(item).strip() for item in comment_ids if str(item).strip()]
        if not ids:
            return []
        unique_ids = list(dict.fromkeys(ids))[: max(min(limit, 500), 1)]
        return list(
            self.session.scalars(
                select(ContentComment)
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
                .where(ContentComment.comment_id.in_(unique_ids))
                .order_by(ContentComment.last_seen_at.desc(), ContentComment.id.desc())
            ).all()
        )

    def search_comments(
        self,
        *,
        platform: str,
        content_id: str | None = None,
        comment_text_contains: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[ContentComment]:
        stmt = (
            select(ContentComment)
            .where(ContentComment.tenant_id == self.tenant_id)
            .where(ContentComment.platform == platform)
        )
        if content_id:
            stmt = stmt.where(ContentComment.content_id == content_id)
        text = (comment_text_contains or "").strip()
        if text:
            stmt = stmt.where(ContentComment.comment_text.contains(text[:80]))
        stmt = (
            stmt.order_by(ContentComment.last_seen_at.desc(), ContentComment.id.desc())
            .offset(max(offset, 0))
            .limit(max(min(limit, 50), 1))
        )
        return list(self.session.scalars(stmt).all())

    def get_by_comment_id(self, *, platform: str, content_id: str, comment_id: str) -> ContentComment | None:
        return self.session.scalar(
            select(ContentComment)
            .where(ContentComment.tenant_id == self.tenant_id)
            .where(ContentComment.platform == platform)
            .where(ContentComment.content_id == content_id)
            .where(ContentComment.comment_id == comment_id)
            .limit(1)
        )

    def find_comment_record(
        self,
        *,
        platform: str,
        comment_id: str,
        content_id: str | None = None,
        comment_text: str | None = None,
    ) -> ContentComment | None:
        stmt = (
            select(ContentComment)
            .where(ContentComment.tenant_id == self.tenant_id)
            .where(ContentComment.platform == platform)
            .where(ContentComment.comment_id == comment_id)
        )
        if content_id:
            stmt = stmt.where(ContentComment.content_id == content_id)
        rows = list(self.session.scalars(stmt.order_by(ContentComment.last_seen_at.desc())).all())
        if not rows and comment_text:
            fuzzy = (
                select(ContentComment)
                .where(ContentComment.tenant_id == self.tenant_id)
                .where(ContentComment.platform == platform)
                .where(ContentComment.comment_text.contains(comment_text.strip()[:80]))
            )
            if content_id:
                fuzzy = fuzzy.where(ContentComment.content_id == content_id)
            rows = list(self.session.scalars(fuzzy.order_by(ContentComment.last_seen_at.desc()).limit(5)).all())
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]
        with_url = [row for row in rows if row.content_url]
        return with_url[0] if with_url else rows[0]

    def upsert_comment(
        self,
        *,
        platform: str,
        content_id: str,
        comment_id: str,
        parent_comment_id: str | None,
        nickname: str,
        comment_text: str,
        digg_count: int,
        create_time: int | None,
        content_url: str | None,
        raw_data: dict | None,
        now: datetime,
    ) -> tuple[ContentComment, bool, bool]:
        row = self.get_by_comment_id(platform=platform, content_id=content_id, comment_id=comment_id)
        if row is None:
            row = ContentComment(
                tenant_id=self.tenant_id,
                platform=platform,
                content_id=content_id,
                comment_id=comment_id,
                parent_comment_id=parent_comment_id,
                nickname=nickname,
                comment_text=comment_text,
                digg_count=digg_count,
                create_time=create_time,
                content_url=content_url,
                raw_data=raw_data,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(row)
            self.session.flush()
            return row, True, False

        changed = (
            row.nickname != nickname
            or row.comment_text != comment_text
            or int(row.digg_count or 0) != int(digg_count or 0)
            or row.parent_comment_id != parent_comment_id
        )
        row.nickname = nickname
        row.comment_text = comment_text
        row.digg_count = digg_count
        row.create_time = create_time or row.create_time
        row.parent_comment_id = parent_comment_id
        row.content_url = content_url or row.content_url
        row.raw_data = raw_data or row.raw_data
        row.last_seen_at = now
        self.session.flush()
        return row, False, changed

    def delete_comment(self, *, platform: str, content_id: str, comment_id: str) -> bool:
        row = self.get_by_comment_id(platform=platform, content_id=content_id, comment_id=comment_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def delete_content_comments(self, *, platform: str, content_id: str) -> int:
        rows = self.list_by_content(platform=platform, content_id=content_id)
        for row in rows:
            self.session.delete(row)
        if rows:
            self.session.flush()
        return len(rows)

    def update_comment_fields(
        self,
        *,
        platform: str,
        content_id: str,
        comment_id: str,
        nickname: str | None = None,
        comment_text: str | None = None,
        digg_count: int | None = None,
        parent_comment_id: str | None = None,
        content_url: str | None = None,
        raw_data: dict | None = None,
        create_time: int | None = None,
        now: datetime | None = None,
    ) -> ContentComment | None:
        row = self.get_by_comment_id(platform=platform, content_id=content_id, comment_id=comment_id)
        if row is None:
            return None
        if nickname is not None:
            row.nickname = nickname
        if comment_text is not None:
            row.comment_text = comment_text
        if digg_count is not None:
            row.digg_count = digg_count
        if parent_comment_id is not None:
            row.parent_comment_id = parent_comment_id
        if content_url is not None:
            row.content_url = content_url
        if raw_data is not None:
            row.raw_data = raw_data
        if create_time is not None:
            row.create_time = create_time
        row.last_seen_at = now or datetime.utcnow()
        self.session.flush()
        return row
