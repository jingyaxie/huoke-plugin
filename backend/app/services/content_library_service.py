from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.content_comment_repository import ContentCommentRepository
from app.schemas.content_library import (
    CommentItemOut,
    CommentUserOut,
    ContentDetailOut,
    ContentListResponse,
    ContentMetaOut,
    ContentSummaryOut,
    KeywordContextOut,
)
from app.services.comment_store_service import CommentStoreService

_CANONICAL_FILE_RE = re.compile(
    r"^comments_(?P<platform>[a-z]+)_(?P<tenant>[^_]+)_(?P<content_id>.+)\.json$",
    re.IGNORECASE,
)

_PLATFORM_ID_KEYS = ("aweme_id", "note_id", "photo_id", "content_id", "external_id")
_META_SCALAR_KEYS = (
    "title",
    "author",
    "author_name",
    "author_id",
    "cover_url",
    "capture_method",
    "warning",
    "guest_mode",
    "session_mode",
)
_COUNT_KEYS = {
    "like_count": ("like_count", "digg_count"),
    "share_count": ("share_count",),
    "publish_time": ("publish_time", "create_time"),
    "api_total_top_comments": ("api_total_top_comments",),
}


def _first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def _extract_external_id(content_id: str, payload: dict[str, Any]) -> str | None:
    value = _first_value(payload, *_PLATFORM_ID_KEYS)
    if value is not None:
        return str(value)
    if "_" in content_id:
        base = content_id.rsplit("_", 2)[0]
        if base:
            return base
    return content_id or None


def _keyword_context(payload: dict[str, Any]) -> KeywordContextOut | None:
    raw = payload.get("keyword_context")
    if not isinstance(raw, dict):
        keyword = payload.get("keyword")
        if not keyword:
            return None
        return KeywordContextOut(keyword=str(keyword))
    return KeywordContextOut(
        keyword=_first_value(raw, "keyword"),
        search_keyword=_first_value(raw, "search_keyword"),
        days=int(raw["days"]) if raw.get("days") is not None else None,
        region=_first_value(raw, "region"),
        guest_mode=raw.get("guest_mode") if isinstance(raw.get("guest_mode"), bool) else None,
        session_mode=_first_value(raw, "session_mode"),
    )


def _extract_meta(
    *,
    platform: str,
    content_id: str,
    payload: dict[str, Any] | None,
    path: Path | None = None,
) -> ContentMetaOut:
    data = payload or {}
    keyword_ctx = _keyword_context(data)
    guest_mode = data.get("guest_mode")
    if guest_mode is None and keyword_ctx is not None:
        guest_mode = keyword_ctx.guest_mode
    session_mode = _first_value(data, "session_mode")
    if session_mode is None and keyword_ctx is not None:
        session_mode = keyword_ctx.session_mode

    author_name = _first_value(data, "author_name", "author")
    if isinstance(author_name, dict):
        author_name = _first_value(author_name, "nickname", "name", "unique_id")

    file_modified_at = None
    if path is not None and path.exists():
        file_modified_at = datetime.fromtimestamp(path.stat().st_mtime)

    known = {
        "platform",
        "content_id",
        "tenant_id",
        "comments",
        "storage_meta",
        "total_comments_captured",
        "top_comments_captured",
        "reply_comments_captured_preview",
        "expected_reply_total_from_top_comments",
        "keyword_context",
        *_PLATFORM_ID_KEYS,
        *_META_SCALAR_KEYS,
        *{key for group in _COUNT_KEYS.values() for key in group},
        "video_url",
        "note_url",
        "content_url",
    }
    extra = {key: value for key, value in data.items() if key not in known and value is not None}

    return ContentMetaOut(
        platform=str(data.get("platform") or platform),
        external_id=_extract_external_id(content_id, data),
        title=_first_value(data, "title"),
        author_name=str(author_name) if author_name else None,
        author_id=str(v) if (v := _first_value(data, "author_id", "sec_uid", "photo_author_id")) else None,
        cover_url=_first_value(data, "cover_url"),
        content_url=_first_value(data, "video_url", "note_url", "content_url"),
        video_url=_first_value(data, "video_url"),
        note_url=_first_value(data, "note_url"),
        like_count=int(v) if (v := _first_value(data, *_COUNT_KEYS["like_count"])) is not None else None,
        share_count=int(v) if (v := _first_value(data, *_COUNT_KEYS["share_count"])) is not None else None,
        publish_time=int(v) if (v := _first_value(data, *_COUNT_KEYS["publish_time"])) is not None else None,
        capture_method=_first_value(data, "capture_method"),
        api_total_top_comments=int(v)
        if (v := _first_value(data, *_COUNT_KEYS["api_total_top_comments"])) is not None
        else None,
        keyword_context=keyword_ctx,
        warning=_first_value(data, "warning"),
        guest_mode=guest_mode if isinstance(guest_mode, bool) else None,
        session_mode=str(session_mode) if session_mode else None,
        file_modified_at=file_modified_at,
        extra=extra or None,
    )


def _nickname(row: dict[str, Any]) -> str:
    for key in ("nickname", "username", "user_name", "nick_name"):
        val = row.get(key)
        if val:
            return str(val).strip()
    return "未知用户"


def _comment_user(row: dict[str, Any]) -> CommentUserOut:
    username = _nickname(row)
    user_id = row.get("user_id") or row.get("authorId") or row.get("author_id")
    sec_uid = row.get("sec_uid")
    avatar = row.get("avatar")
    author = row.get("author")
    if isinstance(author, dict):
        user_id = user_id or author.get("id") or author.get("authorId")
        avatar = avatar or author.get("headurl") or author.get("avatar")
        username = username if username != "未知用户" else str(author.get("name") or username)
    user = row.get("user")
    if isinstance(user, dict):
        user_id = user_id or user.get("uid") or user.get("user_id")
        sec_uid = sec_uid or user.get("sec_uid")
        avatar = avatar or user.get("avatar_thumb", {}).get("url_list", [None])[0] if isinstance(user.get("avatar_thumb"), dict) else user.get("avatar")
        username = username if username != "未知用户" else str(user.get("nickname") or user.get("unique_id") or username)
    return CommentUserOut(
        user_id=str(user_id) if user_id else None,
        sec_uid=str(sec_uid) if sec_uid else None,
        username=username,
        avatar=str(avatar) if avatar else None,
    )


def _normalize_naive_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _resolve_updated_at(
    *,
    last_seen_at: datetime | None,
    file_modified_at: datetime | None,
) -> datetime | None:
    candidates = [
        _normalize_naive_dt(value)
        for value in (last_seen_at, file_modified_at)
        if value is not None
    ]
    return max(candidates) if candidates else None


def _comment_item(row: dict[str, Any]) -> CommentItemOut:
    text = str(row.get("comment") or row.get("text") or row.get("comment_text") or "").strip()
    photo_author_id = row.get("photo_author_id")
    return CommentItemOut(
        comment_id=str(row.get("comment_id") or ""),
        parent_comment_id=str(row["parent_comment_id"]) if row.get("parent_comment_id") else None,
        comment=text,
        nickname=_nickname(row),
        digg_count=int(row.get("digg_count") or 0),
        create_time=int(row["create_time"]) if row.get("create_time") is not None else None,
        reply_comment_total=int(row.get("reply_comment_total") or 0),
        photo_author_id=str(photo_author_id).strip() if photo_author_id else None,
        user=_comment_user(row),
    )


class ContentLibraryService:
    def __init__(self, session: Session, settings: Settings, *, tenant_id: str) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id

    def _canonical_path(self, platform: str, content_id: str) -> Path:
        return self.settings.report_output_dir / f"comments_{platform}_{self.tenant_id}_{content_id}.json"

    def _scan_canonical_files(self, platform: str) -> dict[str, Path]:
        root = self.settings.report_output_dir
        if not root.exists():
            return {}
        pattern = f"comments_{platform}_{self.tenant_id}_*.json"
        found: dict[str, Path] = {}
        for path in root.glob(pattern):
            match = _CANONICAL_FILE_RE.match(path.name)
            if match is None:
                continue
            if match.group("platform") != platform or match.group("tenant") != self.tenant_id:
                continue
            found[match.group("content_id")] = path
        return found

    def _build_summary(
        self,
        *,
        platform: str,
        content_id: str,
        path: Path | None,
        content_url: str | None = None,
        comment_count: int = 0,
        top_comment_count: int = 0,
        last_seen_at: datetime | None = None,
        full_payload: dict[str, Any] | None = None,
    ) -> ContentSummaryOut:
        payload = {key: value for key, value in (full_payload or {}).items() if key != "comments"}
        meta = _extract_meta(platform=platform, content_id=content_id, payload=payload or None, path=path)
        updated_at = _resolve_updated_at(last_seen_at=last_seen_at, file_modified_at=meta.file_modified_at)
        return ContentSummaryOut(
            content_id=content_id,
            platform=platform,
            tenant_id=self.tenant_id,
            content_url=content_url or meta.content_url,
            comment_count=comment_count,
            top_comment_count=top_comment_count,
            last_seen_at=last_seen_at,
            updated_at=updated_at,
            canonical_file=path.name if path is not None else None,
            meta=meta,
        )

    def list_contents(
        self,
        *,
        platform: str,
        offset: int = 0,
        limit: int = 50,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> ContentListResponse:
        repo = ContentCommentRepository(self.session, self.tenant_id, platform)
        rows = repo.list_all_content_summaries(platform=platform)
        canonical_map = self._scan_canonical_files(platform)
        items_by_id: dict[str, ContentSummaryOut] = {}

        for row in rows:
            path = canonical_map.get(row.content_id)
            payload = self._load_payload_meta_from_file(path) if path is not None else None
            items_by_id[row.content_id] = self._build_summary(
                platform=platform,
                content_id=row.content_id,
                path=path,
                content_url=row.content_url or (payload or {}).get("video_url") or (payload or {}).get("note_url"),
                comment_count=row.comment_count,
                top_comment_count=row.top_comment_count,
                last_seen_at=row.last_seen_at,
                full_payload=payload,
            )

        for content_id, path in canonical_map.items():
            if content_id in items_by_id:
                continue
            full_payload = self._load_payload_from_file(path)
            comment_count = 0
            top_comment_count = 0
            content_url = None
            if full_payload is not None:
                content_url = full_payload.get("video_url") or full_payload.get("note_url")
                comments = full_payload.get("comments") or []
                comment_count = len(comments)
                top_comment_count = len([row for row in comments if not row.get("parent_comment_id")])
            items_by_id[content_id] = self._build_summary(
                platform=platform,
                content_id=content_id,
                path=path,
                content_url=content_url,
                comment_count=comment_count,
                top_comment_count=top_comment_count,
                full_payload=full_payload,
            )

        items = list(items_by_id.values())
        after = _normalize_naive_dt(updated_after)
        before = _normalize_naive_dt(updated_before)
        if after is not None:
            items = [item for item in items if item.updated_at is not None and item.updated_at >= after]
        if before is not None:
            items = [item for item in items if item.updated_at is not None and item.updated_at <= before]

        items.sort(key=lambda item: item.updated_at or datetime.min, reverse=True)
        total = len(items)
        page = items[offset : offset + limit]
        return ContentListResponse(platform=platform, tenant_id=self.tenant_id, total=total, items=page)

    def _load_payload_from_file(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _load_payload_meta_from_file(self, path: Path) -> dict[str, Any] | None:
        payload = self._load_payload_from_file(path)
        if payload is None:
            return None
        return {key: value for key, value in payload.items() if key != "comments"}

    def get_content_detail(
        self,
        *,
        platform: str,
        content_id: str,
        max_comments: int | None = None,
    ) -> ContentDetailOut | None:
        canonical = self._canonical_path(platform, content_id)
        payload = self._load_payload_from_file(canonical)
        if payload is None:
            scanned = self._scan_canonical_files(platform)
            alt = scanned.get(content_id)
            if alt is not None:
                payload = self._load_payload_from_file(alt)
                if payload is not None:
                    canonical = alt
        if payload is None:
            store = CommentStoreService(self.session, self.settings, self.tenant_id)
            payload = store.load_payload_from_db(platform=platform, content_id=content_id, max_comments=max_comments)
        if payload is None:
            return None
        comments = [_comment_item(row) for row in (payload.get("comments") or []) if isinstance(row, dict)]
        content_url = payload.get("video_url") or payload.get("note_url")
        meta = _extract_meta(platform=platform, content_id=content_id, payload=payload, path=canonical)
        return ContentDetailOut(
            platform=platform,
            tenant_id=self.tenant_id,
            content_id=content_id,
            content_url=content_url,
            video_url=payload.get("video_url"),
            note_url=payload.get("note_url"),
            total_comments_captured=int(payload.get("total_comments_captured") or len(comments)),
            top_comments_captured=int(
                payload.get("top_comments_captured")
                or len([row for row in comments if not row.parent_comment_id])
            ),
            capture_method=payload.get("capture_method"),
            canonical_file=canonical.name if canonical.exists() else None,
            comments=comments,
            storage_meta=payload.get("storage_meta"),
            meta=meta,
        )
