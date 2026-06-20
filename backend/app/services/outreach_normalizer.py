from __future__ import annotations

from typing import Any


def normalize_crawl_results(
    results: list[dict[str, Any]],
    *,
    task_id: str,
    keyword: str,
    platform: str,
) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    for payload in results:
        content_id = str(payload.get("aweme_id") or payload.get("content_id") or "")
        content_url = str(payload.get("video_url") or payload.get("content_url") or "")
        title = payload.get("title") or payload.get("desc")
        keyword_ctx = payload.get("keyword_context") if isinstance(payload.get("keyword_context"), dict) else {}
        for row in payload.get("comments") or []:
            if not isinstance(row, dict):
                continue
            comment_id = str(row.get("comment_id") or "").strip()
            if not comment_id:
                continue
            if row.get("parent_comment_id"):
                continue
            nickname = str(row.get("nickname") or row.get("username") or "用户")
            leads.append(
                {
                    "platform": platform,
                    "task_id": task_id,
                    "keyword": keyword,
                    "content": {
                        "content_id": content_id,
                        "content_url": content_url,
                        "title": title,
                        "keyword_context": keyword_ctx or {"keyword": keyword},
                        "capture_method": payload.get("capture_method"),
                    },
                    "comment": {
                        "comment_id": comment_id,
                        "parent_comment_id": row.get("parent_comment_id"),
                        "text": str(row.get("comment") or row.get("text") or ""),
                        "create_time": row.get("create_time"),
                        "digg_count": row.get("digg_count"),
                    },
                    "comment_user": {
                        "user_id": str(row.get("user_id") or ""),
                        "sec_uid": str(row.get("sec_uid") or ""),
                        "nickname": nickname,
                        "avatar": row.get("avatar"),
                    },
                    "raw": row,
                    "matched": False,
                    "match_reason": "",
                    "actions_taken": [],
                }
            )
    return leads
