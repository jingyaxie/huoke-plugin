from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.content_comment import ContentComment
from app.platforms.kuaishou.utils import extract_comment_user_id as ks_extract_comment_user_id
from app.repositories.content_comment_repository import ContentCommentRepository
from app.services.content_library_service import ContentLibraryService


def _extract_reply_user_id(platform: str, raw: dict[str, Any]) -> str | None:
    if platform == "kuaishou":
        uid = ks_extract_comment_user_id(raw)
        if uid:
            return uid
    for key in ("user_id", "authorId", "author_id", "uid"):
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    user = raw.get("user")
    if isinstance(user, dict):
        for key in ("user_id", "uid", "id"):
            val = user.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return None


def _serialize_comment(record: ContentComment, *, platform: str) -> dict[str, Any]:
    raw = record.raw_data if isinstance(record.raw_data, dict) else {}
    user_id = _extract_reply_user_id(platform, raw)
    sec_uid = str(raw.get("sec_uid") or "").strip()
    if not sec_uid:
        user = raw.get("user")
        if isinstance(user, dict):
            sec_uid = str(user.get("sec_uid") or "").strip()
    return {
        "comment_id": record.comment_id,
        "content_id": record.content_id,
        "content_url": record.content_url,
        "parent_comment_id": record.parent_comment_id,
        "nickname": record.nickname,
        "comment": record.comment_text,
        "digg_count": record.digg_count,
        "create_time": record.create_time,
        "reply_to_user_id": user_id,
        "user_id": user_id,
        "sec_uid": sec_uid or None,
        "photo_author_id": raw.get("photo_author_id") or raw.get("author_id"),
        "last_seen_at": record.last_seen_at.isoformat(timespec="seconds") if record.last_seen_at else None,
        "raw_data": raw,
    }


class StoredCommentService:
    """从 MySQL content_comments 表查询已入库评论（Agent / builtin 共用）。"""

    def __init__(self, session: Session, settings: Settings, *, tenant_id: str) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id

    def query_contents(
        self,
        *,
        platform: str,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        library = ContentLibraryService(self.session, self.settings, tenant_id=self.tenant_id)
        result = library.list_contents(platform=platform, offset=offset, limit=min(limit, 50))
        items = []
        for item in result.items:
            items.append(
                {
                    "content_id": item.content_id,
                    "content_url": item.content_url,
                    "comment_count": item.comment_count,
                    "top_comment_count": item.top_comment_count,
                    "updated_at": item.updated_at.isoformat(timespec="seconds") if item.updated_at else None,
                    "title": item.meta.title if item.meta else None,
                    "author_name": item.meta.author_name if item.meta else None,
                }
            )
        return {
            "source": "database",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "total": result.total,
            "offset": offset,
            "limit": limit,
            "items": items,
        }

    def query_comments(
        self,
        *,
        platform: str,
        content_id: str | None = None,
        comment_text_contains: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        rows = repo.search_comments(
            platform=platform,
            content_id=content_id,
            comment_text_contains=comment_text_contains,
            offset=offset,
            limit=min(limit, 50),
        )
        return {
            "source": "database",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "content_id": content_id,
            "comment_text_contains": comment_text_contains,
            "offset": offset,
            "limit": limit,
            "count": len(rows),
            "comments": [_serialize_comment(row, platform=platform) for row in rows],
        }

    def get_content_detail(
        self,
        *,
        platform: str,
        content_id: str,
        max_comments: int = 50,
    ) -> dict[str, Any] | None:
        library = ContentLibraryService(self.session, self.settings, tenant_id=self.tenant_id)
        detail = library.get_content_detail(
            platform=platform,
            content_id=content_id,
            max_comments=min(max_comments, 100),
        )
        if detail is None:
            return None
        return {
            "source": "database",
            "platform": detail.platform,
            "tenant_id": detail.tenant_id,
            "content_id": detail.content_id,
            "content_url": detail.content_url,
            "total_comments_captured": detail.total_comments_captured,
            "comments": [
                {
                    "comment_id": row.comment_id,
                    "nickname": row.nickname,
                    "comment": row.comment,
                    "reply_to_user_id": row.user.user_id if row.user else None,
                    "photo_author_id": row.photo_author_id,
                    "digg_count": row.digg_count,
                    "create_time": row.create_time,
                }
                for row in detail.comments
            ],
        }

    def get_comment(
        self,
        *,
        platform: str,
        comment_id: str,
        content_id: str | None = None,
    ) -> dict[str, Any]:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        row = repo.find_comment_record(
            platform=platform,
            comment_id=comment_id,
            content_id=content_id,
        )
        if row is None:
            return {
                "source": "database",
                "status": "not_found",
                "platform": platform,
                "tenant_id": self.tenant_id,
                "comment_id": comment_id,
                "content_id": content_id,
                "error": "评论不存在",
            }
        return {
            "source": "database",
            "status": "ok",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "comment": _serialize_comment(row, platform=platform),
        }

    def create_comment(
        self,
        *,
        platform: str,
        content_id: str,
        comment_id: str,
        comment_text: str,
        nickname: str = "",
        content_url: str | None = None,
        parent_comment_id: str | None = None,
        digg_count: int = 0,
        create_time: int | None = None,
        raw_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        now = datetime.utcnow()
        row, created, changed = repo.upsert_comment(
            platform=platform,
            content_id=content_id,
            comment_id=comment_id,
            parent_comment_id=parent_comment_id,
            nickname=nickname or "",
            comment_text=comment_text,
            digg_count=int(digg_count or 0),
            create_time=create_time,
            content_url=content_url,
            raw_data=raw_data,
            now=now,
        )
        self.session.commit()
        action = "created" if created else ("updated" if changed else "unchanged")
        return {
            "source": "database",
            "status": "ok",
            "action": action,
            "platform": platform,
            "tenant_id": self.tenant_id,
            "comment": _serialize_comment(row, platform=platform),
        }

    def update_comment(
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
        raw_data: dict[str, Any] | None = None,
        create_time: int | None = None,
    ) -> dict[str, Any]:
        if all(
            v is None
            for v in (
                nickname,
                comment_text,
                digg_count,
                parent_comment_id,
                content_url,
                raw_data,
                create_time,
            )
        ):
            return {"error": "至少提供一个要更新的字段", "status": "failed", "source": "database"}

        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        row = repo.update_comment_fields(
            platform=platform,
            content_id=content_id,
            comment_id=comment_id,
            nickname=nickname,
            comment_text=comment_text,
            digg_count=digg_count,
            parent_comment_id=parent_comment_id,
            content_url=content_url,
            raw_data=raw_data,
            create_time=create_time,
        )
        if row is None:
            return {
                "source": "database",
                "status": "not_found",
                "error": "评论不存在",
                "platform": platform,
                "content_id": content_id,
                "comment_id": comment_id,
            }
        self.session.commit()
        return {
            "source": "database",
            "status": "ok",
            "action": "updated",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "comment": _serialize_comment(row, platform=platform),
        }

    def delete_comment(
        self,
        *,
        platform: str,
        content_id: str,
        comment_id: str,
    ) -> dict[str, Any]:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        deleted = repo.delete_comment(
            platform=platform,
            content_id=content_id,
            comment_id=comment_id,
        )
        if not deleted:
            return {
                "source": "database",
                "status": "not_found",
                "error": "评论不存在",
                "platform": platform,
                "content_id": content_id,
                "comment_id": comment_id,
            }
        self.session.commit()
        return {
            "source": "database",
            "status": "ok",
            "action": "deleted",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "content_id": content_id,
            "comment_id": comment_id,
            "deleted_count": 1,
        }

    def delete_content(
        self,
        *,
        platform: str,
        content_id: str,
    ) -> dict[str, Any]:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        deleted_count = repo.delete_content_comments(platform=platform, content_id=content_id)
        if deleted_count == 0:
            return {
                "source": "database",
                "status": "not_found",
                "error": "该内容下无已入库评论",
                "platform": platform,
                "content_id": content_id,
                "deleted_count": 0,
            }
        self.session.commit()
        return {
            "source": "database",
            "status": "ok",
            "action": "deleted",
            "platform": platform,
            "tenant_id": self.tenant_id,
            "content_id": content_id,
            "deleted_count": deleted_count,
        }
