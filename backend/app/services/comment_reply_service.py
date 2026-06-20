from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.platforms.douyin.js_constants import _extract_aweme_id
from app.platforms.kuaishou.utils import build_video_url, extract_comment_user_id, find_comment_author_id
from app.platforms.registry import get_reply_comment_tool
from app.platforms.types import normalize_platform
from app.platforms.xiaohongshu.utils import build_note_url, extract_note_access_params, extract_note_id
from app.repositories.content_comment_repository import ContentCommentRepository
from app.services.comment_store_service import CommentStoreService, extract_content_id


@dataclass
class CommentReplyTarget:
    platform: str
    comment_id: str
    content_id: str
    content_url: str
    comment_text: str = ""
    parent_comment_id: str | None = None
    nickname: str = ""
    photo_author_id: str | None = None
    reply_to_user_id: str | None = None


class CommentReplyService:
    """从 DB 定位评论所属内容，再经页面 JS 接口直接回复。"""

    def __init__(
        self,
        settings: Settings,
        *,
        tenant_id: str,
        platform: str,
        session: Session,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = normalize_platform(platform)
        self.session = session
        self.account_id = account_id
        self.repo = ContentCommentRepository(session, tenant_id)

    def _photo_author_from_payload(self, data: dict | None) -> str | None:
        if not isinstance(data, dict):
            return None
        val = data.get("photo_author_id") or data.get("author_id")
        return str(val).strip() if val else None

    def _photo_author_from_canonical(self, content_id: str) -> str | None:
        if self.platform != "kuaishou" or not content_id:
            return None
        path = self.settings.report_output_dir / f"comments_{self.platform}_{self.tenant_id}_{content_id}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                found = self._photo_author_from_payload(data)
                if found:
                    return found
            except Exception:
                pass
        pattern = f"comments_{self.platform}_{self.tenant_id}_{content_id}_*.json"
        for candidate in sorted(self.settings.report_output_dir.glob(pattern), reverse=True):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                found = self._photo_author_from_payload(data)
                if found:
                    return found
            except Exception:
                continue
        store = CommentStoreService(self.session, self.settings, self.tenant_id)
        payload = store.load_payload_from_db(platform=self.platform, content_id=content_id)
        return self._photo_author_from_payload(payload)

    def _load_canonical_payload(self, content_id: str) -> dict | None:
        if not content_id:
            return None
        path = self.settings.report_output_dir / f"comments_{self.platform}_{self.tenant_id}_{content_id}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        pattern = f"comments_{self.platform}_{self.tenant_id}_{content_id}_*.json"
        for candidate in sorted(self.settings.report_output_dir.glob(pattern), reverse=True):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        store = CommentStoreService(self.session, self.settings, self.tenant_id)
        return store.load_payload_from_db(platform=self.platform, content_id=content_id)

    def _reply_to_user_from_payload(self, data: dict | None, comment_id: str) -> str | None:
        if not isinstance(data, dict):
            return None
        rows = data.get("comments") or []
        if isinstance(rows, list):
            found = find_comment_author_id([row for row in rows if isinstance(row, dict)], comment_id)
            if found:
                return found
        return None

    def _reply_to_user_from_stored(
        self,
        *,
        raw: dict,
        content_id: str,
        comment_id: str,
    ) -> str | None:
        uid = extract_comment_user_id(raw)
        if uid:
            return uid
        payload = self._load_canonical_payload(content_id)
        found = self._reply_to_user_from_payload(payload, comment_id)
        if found:
            return found
        rows = self.repo.list_by_content(platform=self.platform, content_id=content_id)
        for row in rows:
            if str(row.comment_id) != str(comment_id):
                continue
            raw_row = row.raw_data if isinstance(row.raw_data, dict) else {}
            uid = extract_comment_user_id(raw_row)
            if uid:
                return uid
        return None

    def _photo_author_from_sibling_comments(self, content_id: str) -> str | None:
        rows = self.repo.list_by_content(platform=self.platform, content_id=content_id)
        for row in rows:
            raw = row.raw_data if isinstance(row.raw_data, dict) else {}
            val = raw.get("photo_author_id") or raw.get("author_id")
            if val:
                return str(val).strip()
        return None

    def resolve_target(
        self,
        *,
        comment_id: str,
        content_id: str | None = None,
        comment_text: str | None = None,
        video_url: str | None = None,
        note_url: str | None = None,
        content_url: str | None = None,
        photo_author_id: str | None = None,
        reply_to_user_id: str | None = None,
    ) -> CommentReplyTarget | dict[str, Any]:
        comment_id = str(comment_id or "").strip()
        text_hint = (comment_text or "").strip()
        url_override = (video_url or note_url or content_url or "").strip() or None

        if not comment_id and text_hint and url_override:
            resolved_content_id = str(content_id or extract_content_id(self.platform, url_override) or "")
            if not resolved_content_id:
                return {"error": "无法从链接解析 content_id", "status": "failed"}
            return CommentReplyTarget(
                platform=self.platform,
                comment_id=f"ui-{abs(hash(text_hint)) % 10**16}",
                content_id=resolved_content_id,
                content_url=url_override,
                comment_text=text_hint,
                photo_author_id=str(photo_author_id).strip() if photo_author_id else None,
                reply_to_user_id=str(reply_to_user_id).strip() if reply_to_user_id else None,
            )

        if not comment_id:
            return {"error": "缺少 comment_id 或 (video_url + comment_text) UI 定位信息", "status": "failed"}

        record = self.repo.find_comment_record(
            platform=self.platform,
            comment_id=comment_id,
            content_id=content_id,
            comment_text=comment_text,
        )

        if record:
            resolved_content_id = str(content_id or record.content_id)
            resolved_url = url_override or (record.content_url or "").strip() or self._default_content_url(
                resolved_content_id,
                fallback_url=url_override,
                raw_data=record.raw_data,
            )
            if not resolved_url:
                return {
                    "error": f"评论 {comment_id} 缺少 content_url，请传入 video_url / note_url",
                    "status": "failed",
                }
            raw = record.raw_data if isinstance(record.raw_data, dict) else {}
            resolved_author = (
                photo_author_id
                or raw.get("photo_author_id")
                or self._photo_author_from_canonical(resolved_content_id)
                or self._photo_author_from_sibling_comments(resolved_content_id)
            )
            resolved_reply_to = (
                str(reply_to_user_id).strip()
                if reply_to_user_id and str(reply_to_user_id).strip()
                else self._reply_to_user_from_stored(
                    raw=raw,
                    content_id=resolved_content_id,
                    comment_id=comment_id,
                )
            )
            return CommentReplyTarget(
                platform=self.platform,
                comment_id=comment_id,
                content_id=resolved_content_id,
                content_url=resolved_url,
                comment_text=record.comment_text or (comment_text or ""),
                parent_comment_id=record.parent_comment_id,
                nickname=record.nickname or "",
                photo_author_id=str(resolved_author).strip() if resolved_author else None,
                reply_to_user_id=resolved_reply_to,
            )

        if url_override:
            resolved_content_id = str(content_id or extract_content_id(self.platform, url_override) or "")
            if not resolved_content_id:
                return {"error": "无法从链接解析 content_id", "status": "failed"}
            resolved_author = (
                photo_author_id
                or self._photo_author_from_canonical(resolved_content_id)
                or self._photo_author_from_sibling_comments(resolved_content_id)
            )
            resolved_reply_to = (
                str(reply_to_user_id).strip()
                if reply_to_user_id and str(reply_to_user_id).strip()
                else self._reply_to_user_from_stored(
                    raw={},
                    content_id=resolved_content_id,
                    comment_id=comment_id,
                )
            )
            return CommentReplyTarget(
                platform=self.platform,
                comment_id=comment_id,
                content_id=resolved_content_id,
                content_url=url_override,
                comment_text=comment_text or "",
                photo_author_id=str(resolved_author).strip() if resolved_author else None,
                reply_to_user_id=resolved_reply_to,
            )

        return {
            "error": (
                f"数据库未找到评论 {comment_id}；请先抓取评论入库，或同时提供 video_url / note_url"
            ),
            "status": "failed",
        }

    def _default_content_url(
        self,
        content_id: str,
        *,
        fallback_url: str | None,
        raw_data: dict[str, Any] | None,
    ) -> str:
        if fallback_url:
            return fallback_url
        if self.platform == "douyin":
            return f"https://www.douyin.com/video/{content_id}"
        if self.platform == "xiaohongshu":
            import json

            from app.platforms.xiaohongshu.utils import resolve_note_open_url
            from app.services.comment_store_service import CommentStoreService

            note_meta: dict[str, Any] | None = None
            try:
                path = CommentStoreService(
                    self.session,
                    self.settings,
                    self.tenant_id,
                ).canonical_file_path(self.platform, content_id)
                if path.exists():
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    note = payload.get("note") if isinstance(payload.get("note"), dict) else {}
                    note_meta = {**payload, **note}
            except Exception:
                note_meta = None
            return resolve_note_open_url(
                content_id,
                content_url=fallback_url,
                raw_data=raw_data,
                note_meta=note_meta,
            )
        if self.platform == "kuaishou":
            return build_video_url(content_id)
        return ""

    async def _reply_douyin_via_warm_publish(
        self,
        target: CommentReplyTarget,
        *,
        reply_text: str,
        page,
        dry_run: bool = True,
    ) -> dict[str, Any] | None:
        from app.services.social_roam.human.douyin.reply_warm_publish import (
            warm_publish_reply_comment,
        )

        aweme_id = target.content_id
        with contextlib.suppress(ValueError):
            aweme_id = _extract_aweme_id(target.content_url)
        try:
            result = await warm_publish_reply_comment(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                content_url=target.content_url,
                comment_id=target.comment_id,
                reply_text=reply_text,
                aweme_id=aweme_id,
                dry_run=dry_run,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "platform": self.platform,
                "comment_id": target.comment_id,
                "error": str(exc),
                "capture_method": "douyin_comment_warm_publish",
            }
        if not result.get("ok"):
            return {
                "status": "failed",
                "platform": self.platform,
                "comment_id": target.comment_id,
                "content_url": target.content_url,
                "error": result.get("error") or "warm_publish 失败",
                "capture_method": result.get("capture_method"),
                "steps": result.get("steps"),
                "would_publish": result.get("would_publish"),
            }
        return {
            "status": "completed",
            "platform": self.platform,
            "comment_id": target.comment_id,
            "content_id": target.content_id,
            "content_url": target.content_url,
            "target_comment_text": target.comment_text,
            "reply_text": reply_text,
            "dry_run": bool(result.get("dry_run")),
            "capture_method": result.get("capture_method"),
            "reply": result,
            "diagnostic": result.get("diagnostic"),
            "would_publish": result.get("would_publish"),
            "steps": result.get("steps"),
            "error": None,
        }

    def _load_xhs_note_meta(self, content_id: str) -> dict[str, Any] | None:
        """合并多份报告元数据，优先保留带 search_url / xsec_token 的字段。"""
        try:
            store = CommentStoreService(self.session, self.settings, self.tenant_id)
            paths: list[Path] = []
            canonical = store.canonical_file_path(self.platform, content_id)
            report_dir = self.settings.report_output_dir
            paths.extend(
                sorted(
                    report_dir.glob(
                        f"comments_{self.platform}_{self.tenant_id}_{content_id}_*.json"
                    ),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            )
            if canonical.exists() and canonical not in paths:
                paths.append(canonical)

            merged: dict[str, Any] | None = None
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                note = payload.get("note") if isinstance(payload.get("note"), dict) else {}
                meta = {**payload, **note}
                if merged is None:
                    merged = dict(meta)
                    continue
                for key in (
                    "search_url",
                    "xsec_token",
                    "xsec_source",
                    "note_url",
                    "content_url",
                    "video_url",
                    "keyword_context",
                ):
                    val = meta.get(key)
                    if val and not merged.get(key):
                        merged[key] = val
            return merged
        except Exception:
            return None
        return None

    async def _reply_xhs_via_warm_publish(
        self,
        target: CommentReplyTarget,
        *,
        reply_text: str,
        page,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        from app.services.social_roam.human.xiaohongshu.reply_warm_publish import (
            warm_publish_reply_comment,
        )

        note_id = target.content_id
        with contextlib.suppress(ValueError):
            note_id = extract_note_id(target.content_url)
        note_meta = self._load_xhs_note_meta(target.content_id)
        try:
            result = await warm_publish_reply_comment(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                content_url=target.content_url,
                comment_id=target.comment_id,
                comment_text=target.comment_text,
                parent_comment_id=target.parent_comment_id or "",
                reply_text=reply_text,
                note_id=note_id,
                dry_run=dry_run,
                note_meta=note_meta,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "platform": self.platform,
                "comment_id": target.comment_id,
                "error": str(exc),
                "capture_method": "xiaohongshu_comment_warm_publish",
            }
        if not result.get("ok"):
            return {
                "status": "failed",
                "platform": self.platform,
                "comment_id": target.comment_id,
                "content_url": target.content_url,
                "error": result.get("error") or "warm_publish 失败",
                "capture_method": result.get("capture_method"),
                "steps": result.get("steps"),
                "would_publish": result.get("would_publish"),
            }
        return {
            "status": "completed",
            "platform": self.platform,
            "comment_id": target.comment_id,
            "content_id": target.content_id,
            "content_url": target.content_url,
            "target_comment_text": target.comment_text,
            "reply_text": reply_text,
            "dry_run": bool(result.get("dry_run")),
            "capture_method": result.get("capture_method"),
            "reply": result,
            "diagnostic": result.get("diagnostic"),
            "would_publish": result.get("would_publish"),
            "steps": result.get("steps"),
            "error": None,
        }

    async def _reply_douyin_via_human_ui(
        self,
        target: CommentReplyTarget,
        *,
        reply_text: str,
        page,
    ) -> dict[str, Any] | None:
        from app.services.social_roam.human.douyin.actions import human_reply_comment

        try:
            result = await human_reply_comment(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                content_url=target.content_url,
                comment_id=target.comment_id,
                reply_text=reply_text,
                comment_text=target.comment_text,
            )
        except Exception as exc:
            return {
                "status": "failed",
                "platform": self.platform,
                "comment_id": target.comment_id,
                "error": str(exc),
                "capture_method": "douyin_comment_ui_human",
            }
        if not result.get("ok"):
            return {
                "status": "failed",
                "platform": self.platform,
                "comment_id": target.comment_id,
                "content_url": target.content_url,
                "error": result.get("error") or "UI 回复失败",
                "capture_method": result.get("capture_method"),
            }
        return {
            "status": "completed",
            "platform": self.platform,
            "comment_id": target.comment_id,
            "content_id": target.content_id,
            "content_url": target.content_url,
            "target_comment_text": target.comment_text,
            "reply_text": reply_text,
            "capture_method": result.get("capture_method") or "douyin_comment_ui_human",
            "reply": result,
            "output_file": result.get("output_file"),
            "error": None,
        }

    async def reply_comment(
        self,
        *,
        comment_id: str,
        reply_text: str,
        content_id: str | None = None,
        comment_text: str | None = None,
        video_url: str | None = None,
        note_url: str | None = None,
        content_url: str | None = None,
        photo_author_id: str | None = None,
        reply_to_user_id: str | None = None,
        show_browser: bool = False,
        page=None,
        prefer_human_ui: bool = True,
        ui_first: bool = False,
        warm_publish: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        reply_text = str(reply_text or "").strip()
        if not reply_text:
            return {"error": "缺少 reply_text", "status": "failed"}

        target = self.resolve_target(
            comment_id=comment_id,
            content_id=content_id,
            comment_text=comment_text,
            video_url=video_url,
            note_url=note_url,
            content_url=content_url,
            photo_author_id=photo_author_id,
            reply_to_user_id=reply_to_user_id,
        )
        if isinstance(target, dict):
            return target

        if self.platform == "douyin":
            from app.core.antibot import uses_native_system_chrome

            use_warm_publish = warm_publish and not uses_native_system_chrome(
                self.settings, headless=False
            )
            if page is not None and use_warm_publish:
                warm_payload = await self._reply_douyin_via_warm_publish(
                    target,
                    reply_text=reply_text,
                    page=page,
                    dry_run=dry_run,
                )
                if warm_payload is not None and warm_payload.get("status") == "completed":
                    return warm_payload
                if ui_first:
                    return {
                        "status": "failed",
                        "error": "warm_publish 失败，ui_first 模式下禁止回退 JS 接口",
                        "platform": self.platform,
                        "comment_id": target.comment_id,
                    }
            if page is not None and prefer_human_ui:
                human_payload = await self._reply_douyin_via_human_ui(
                    target,
                    reply_text=reply_text,
                    page=page,
                )
                if human_payload is not None:
                    return human_payload
                if ui_first:
                    return {
                        "status": "failed",
                        "error": "UI 回复失败，ui_first 模式下禁止回退 JS 接口",
                        "platform": self.platform,
                        "comment_id": target.comment_id,
                    }
            return {
                "status": "failed",
                "error": (
                    "抖音 JS API 评论回复已移除，请使用 warm_publish 或 human_reply_comment（需浏览器 page）"
                    if page is None
                    else "UI 回复失败，JS 接口已移除"
                ),
                "platform": self.platform,
                "comment_id": target.comment_id,
            }
        elif self.platform == "xiaohongshu":
            if page is None:
                return {
                    "status": "failed",
                    "error": "小红书回复需要浏览器 page，请启用 warm_publish",
                    "platform": self.platform,
                    "comment_id": target.comment_id,
                }
            warm_payload = await self._reply_xhs_via_warm_publish(
                target,
                reply_text=reply_text,
                page=page,
                dry_run=dry_run,
            )
            if warm_payload is not None:
                return warm_payload
            return {
                "status": "failed",
                "error": "warm_publish 回复失败",
                "platform": self.platform,
                "comment_id": target.comment_id,
            }
        else:
            tool = get_reply_comment_tool(
                self.settings,
                self.platform,
                self.tenant_id,
                account_id=self.account_id,
            )
            photo_id = target.content_id
            result = await tool.reply_comment(
                comment_id=target.comment_id,
                reply_text=reply_text,
                video_url=target.content_url,
                photo_id=photo_id,
                photo_author_id=target.photo_author_id or photo_author_id,
                reply_to_user_id=target.reply_to_user_id,
                show_browser=show_browser,
            )

        reply = result.get("reply") or {}
        ok = bool(reply.get("ok"))
        return {
            "status": "completed" if ok else "failed",
            "platform": self.platform,
            "comment_id": target.comment_id,
            "content_id": target.content_id,
            "content_url": target.content_url,
            "target_comment_text": target.comment_text,
            "reply_text": reply_text,
            "capture_method": result.get("capture_method") or "thin_nav_js",
            "reply": reply,
            "output_file": result.get("output_file"),
            "error": None if ok else reply.get("error") or reply.get("status_msg") or reply.get("msg"),
        }
