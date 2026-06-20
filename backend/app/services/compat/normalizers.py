"""Field mapping: Huoke internal shapes → TikHub-compatible payloads."""
from __future__ import annotations

from typing import Any


def video_to_aweme(video: dict[str, Any]) -> dict[str, Any]:
    aweme_id = str(
        video.get("aweme_id")
        or video.get("content_id")
        or video.get("note_id")
        or video.get("id")
        or ""
    ).strip()
    author_name = video.get("author") or video.get("author_name") or video.get("nickname") or ""
    if isinstance(author_name, dict):
        author_name = author_name.get("nickname") or ""
    return {
        "aweme_id": aweme_id,
        "desc": video.get("title") or video.get("desc") or "",
        "author": {
            "nickname": str(author_name),
            "sec_uid": str(video.get("sec_uid") or video.get("author_sec_uid") or ""),
            "uid": str(video.get("user_id") or video.get("author_id") or ""),
        },
        "statistics": {
            "digg_count": int(video.get("like_count") or video.get("digg_count") or 0),
            "comment_count": int(video.get("comment_count") or 0),
            "share_count": int(video.get("share_count") or 0),
        },
        "share_url": video.get("video_url") or video.get("note_url") or video.get("share_url") or "",
    }


def videos_to_aweme_list(videos: list[dict[str, Any]]) -> dict[str, Any]:
    awemes = [video_to_aweme(v) for v in videos if isinstance(v, dict)]
    return {"aweme_list": awemes, "has_more": 0, "cursor": 0}


def note_to_xhs_item(note: dict[str, Any]) -> dict[str, Any]:
    note_id = str(note.get("note_id") or note.get("id") or note.get("content_id") or "").strip()
    return {
        "id": note_id,
        "note_id": note_id,
        "xsec_token": note.get("xsec_token") or "",
        "note_card": {
            "display_title": note.get("title") or note.get("desc") or "",
            "user": {
                "nickname": note.get("author") or note.get("author_name") or "",
                "user_id": note.get("user_id") or note.get("author_id") or "",
            },
            "interact_info": {
                "liked_count": str(note.get("like_count") or note.get("digg_count") or 0),
                "comment_count": str(note.get("comment_count") or 0),
            },
        },
        "note_url": note.get("note_url") or note.get("video_url") or "",
    }


def notes_to_xhs_list(notes: list[dict[str, Any]]) -> dict[str, Any]:
    items = [note_to_xhs_item(n) for n in notes if isinstance(n, dict)]
    return {"items": items, "has_more": False, "cursor": ""}


def comment_to_tikhub_douyin(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cid": str(row.get("comment_id") or row.get("cid") or ""),
        "text": row.get("comment") or row.get("text") or "",
        "create_time": row.get("create_time"),
        "digg_count": int(row.get("digg_count") or 0),
        "user": {
            "nickname": row.get("username") or row.get("nickname") or "",
            "uid": str(row.get("user_id") or ""),
            "sec_uid": row.get("sec_uid") or "",
        },
    }


def comments_to_tikhub_douyin(comments: list[dict[str, Any]], *, cursor: int = 0, has_more: int = 0) -> dict[str, Any]:
    rows = [comment_to_tikhub_douyin(c) for c in comments if isinstance(c, dict)]
    return {
        "comments": rows,
        "cursor": cursor,
        "has_more": has_more,
        "total": len(rows),
    }


def comment_to_tikhub_xhs(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("comment_id") or row.get("id") or ""),
        "content": row.get("comment") or row.get("content") or row.get("text") or "",
        "like_count": int(row.get("digg_count") or row.get("like_count") or 0),
        "user_info": {
            "nickname": row.get("username") or row.get("nickname") or "",
            "user_id": str(row.get("user_id") or ""),
        },
    }


def comments_to_tikhub_xhs(comments: list[dict[str, Any]], *, cursor: str = "", has_more: bool = False) -> dict[str, Any]:
    rows = [comment_to_tikhub_xhs(c) for c in comments if isinstance(c, dict)]
    return {
        "comments": rows,
        "cursor": cursor,
        "has_more": has_more,
        "total": len(rows),
    }
