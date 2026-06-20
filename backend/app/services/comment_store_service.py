from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.content_comment_repository import ContentCommentRepository


@dataclass
class CommentMergeStats:
    new_comments_added: int = 0
    updated_comments: int = 0


def extract_content_id(platform: str, content_url: str, payload: dict[str, Any] | None = None) -> str | None:
    payload = payload or {}
    for key in ("aweme_id", "note_id", "photo_id", "content_id"):
        val = payload.get(key)
        if val:
            return str(val)
    url = (content_url or payload.get("video_url") or payload.get("note_url") or "").strip()
    if not url:
        return None
    patterns = {
        "douyin": r"/video/(\d{8,22})",
        "xiaohongshu": r"/(?:explore|discovery/item)/([0-9a-f]{16,32})",
        "kuaishou": r"/short-video/([0-9A-Za-z_-]{5,})",
    }
    pattern = patterns.get(platform)
    if not pattern:
        return None
    match = re.search(pattern, url)
    return match.group(1) if match else None


def _nickname(row: dict[str, Any]) -> str:
    for key in ("nickname", "user_name", "username", "nick_name"):
        val = row.get(key)
        if val:
            return str(val).strip()
    user = row.get("user")
    if isinstance(user, dict):
        for key in ("nickname", "unique_id", "uid"):
            if user.get(key):
                return str(user[key]).strip()
    return "未知用户"


def _comment_text(row: dict[str, Any]) -> str:
    return str(row.get("comment") or row.get("text") or "").strip()


class CommentStoreService:
    """评论增量合并：写入数据库并维护 canonical JSON 文件。"""

    def __init__(self, session: Session, settings: Settings, tenant_id: str) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id

    def canonical_file_path(self, platform: str, content_id: str) -> Path:
        path = self.settings.report_output_dir / f"comments_{platform}_{self.tenant_id}_{content_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def merge_and_persist(
        self,
        *,
        platform: str,
        content_id: str,
        content_url: str,
        fetched_payload: dict[str, Any],
        max_comments: int | None = None,
        source_job_id: str | None = None,
        source_keyword: str | None = None,
    ) -> tuple[dict[str, Any], Path, CommentMergeStats]:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        now = datetime.utcnow()
        stats = CommentMergeStats()
        incoming_rows = [row for row in (fetched_payload.get("comments") or []) if isinstance(row, dict)]
        agent_meta: dict[str, str] = {}
        jid = str(source_job_id or "").strip()
        if jid:
            agent_meta["source_job_id"] = jid
        kw = str(source_keyword or fetched_payload.get("keyword") or "").strip()
        if not kw and isinstance(fetched_payload.get("keyword_context"), dict):
            kw = str(
                fetched_payload["keyword_context"].get("keyword")
                or fetched_payload["keyword_context"].get("search_keyword")
                or ""
            ).strip()
        if kw:
            agent_meta["source_keyword"] = kw

        for row in incoming_rows:
            comment_id = str(row.get("comment_id") or "").strip()
            if not comment_id:
                continue
            parent_comment_id = row.get("parent_comment_id")
            parent_comment_id = str(parent_comment_id).strip() if parent_comment_id else None
            row_raw = dict(row)
            if agent_meta:
                row_raw["_agent_meta"] = {**agent_meta, **(row_raw.get("_agent_meta") or {})}
            if platform == "kuaishou" and fetched_payload.get("photo_author_id"):
                row_raw.setdefault("photo_author_id", fetched_payload.get("photo_author_id"))
            _, is_new, changed = repo.upsert_comment(
                platform=platform,
                content_id=content_id,
                comment_id=comment_id,
                parent_comment_id=parent_comment_id,
                nickname=_nickname(row),
                comment_text=_comment_text(row),
                digg_count=int(row.get("digg_count") or 0),
                create_time=int(row["create_time"]) if row.get("create_time") is not None else None,
                content_url=content_url,
                raw_data=row_raw,
                now=now,
            )
            if is_new:
                stats.new_comments_added += 1
            elif changed:
                stats.updated_comments += 1

        stored_rows = repo.list_by_content(platform=platform, content_id=content_id)
        comments = []
        for stored in stored_rows:
            row = dict(stored.raw_data or {})
            row.setdefault("comment_id", stored.comment_id)
            row.setdefault("parent_comment_id", stored.parent_comment_id)
            row.setdefault("nickname", stored.nickname)
            row.setdefault("comment", stored.comment_text)
            row.setdefault("digg_count", stored.digg_count)
            row.setdefault("create_time", stored.create_time)
            comments.append(row)

        top_rows = [row for row in comments if not row.get("parent_comment_id")]
        if max_comments is not None:
            top_rows = top_rows[:max_comments]
            kept_ids = {row.get("comment_id") for row in top_rows if row.get("comment_id")}
            kept_ids.update(
                row.get("comment_id")
                for row in comments
                if row.get("parent_comment_id") in kept_ids and row.get("comment_id")
            )
            comments = [row for row in comments if row.get("comment_id") in kept_ids]

        merged_payload = {
            **fetched_payload,
            "platform": platform,
            "content_id": content_id,
            "video_url": fetched_payload.get("video_url") or fetched_payload.get("note_url") or content_url,
            "note_url": fetched_payload.get("note_url") or fetched_payload.get("video_url") or content_url,
            "aweme_id": fetched_payload.get("aweme_id") or (content_id if platform == "douyin" else fetched_payload.get("aweme_id")),
            "total_comments_captured": len(comments),
            "top_comments_captured": len([row for row in comments if not row.get("parent_comment_id")]),
            "comments": comments,
            "storage_meta": {
                "canonical": True,
                "last_merged_at": now.isoformat(),
                "db_total_comments": len(stored_rows),
                "new_comments_added": stats.new_comments_added,
                "updated_comments": stats.updated_comments,
            },
        }
        output = self.canonical_file_path(platform, content_id)
        output.write_text(json.dumps(merged_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged_payload, output, stats

    def load_payload_from_db(self, *, platform: str, content_id: str, max_comments: int | None = None) -> dict[str, Any] | None:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        stored_rows = repo.list_by_content(platform=platform, content_id=content_id)
        if not stored_rows:
            return None
        comments = []
        content_url = stored_rows[0].content_url or ""
        for stored in stored_rows:
            row = dict(stored.raw_data or {})
            row.setdefault("comment_id", stored.comment_id)
            row.setdefault("parent_comment_id", stored.parent_comment_id)
            row.setdefault("nickname", stored.nickname)
            row.setdefault("comment", stored.comment_text)
            row.setdefault("digg_count", stored.digg_count)
            row.setdefault("create_time", stored.create_time)
            comments.append(row)
        top_rows = [row for row in comments if not row.get("parent_comment_id")]
        if max_comments is not None:
            top_rows = top_rows[:max_comments]
            kept_ids = {row.get("comment_id") for row in top_rows if row.get("comment_id")}
            kept_ids.update(
                row.get("comment_id")
                for row in comments
                if row.get("parent_comment_id") in kept_ids and row.get("comment_id")
            )
            comments = [row for row in comments if row.get("comment_id") in kept_ids]
        photo_author_id = next(
            (str(row.get("photo_author_id")).strip() for row in comments if row.get("photo_author_id")),
            "",
        ) or None
        payload: dict[str, Any] = {
            "platform": platform,
            "content_id": content_id,
            "video_url": content_url,
            "note_url": content_url,
            "total_comments_captured": len(comments),
            "top_comments_captured": len([row for row in comments if not row.get("parent_comment_id")]),
            "api_total_top_comments": len([row for row in comments if not row.get("parent_comment_id")]),
            "capture_method": "db_cache",
            "comments": comments,
            "storage_meta": {
                "canonical": True,
                "from_db": True,
                "db_total_comments": len(stored_rows),
            },
        }
        if photo_author_id:
            payload["photo_author_id"] = photo_author_id
        return payload
