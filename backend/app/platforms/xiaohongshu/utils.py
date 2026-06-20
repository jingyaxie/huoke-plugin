from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from app.utils.parsers import parse_count


def extract_note_id(url_or_path: str) -> str:
    from app.platforms.xiaohongshu.constants import NOTE_URL_PATTERN

    match = NOTE_URL_PATTERN.search(url_or_path)
    if not match:
        raise ValueError(f"无法从小红书链接解析 note_id: {url_or_path}")
    return match.group(1)


def extract_note_access_params(url_or_path: str) -> dict[str, str]:
    """从笔记链接解析 xsec_token / xsec_source，评论接口与页面访问均依赖它们。"""
    query = parse_qs(urlsplit(url_or_path).query)
    out: dict[str, str] = {}
    for key in ("xsec_token", "xsec_source"):
        values = query.get(key) or []
        if values and str(values[0]).strip():
            out[key] = str(values[0]).strip()
    return out


def build_note_url(note_id: str, xsec_token: str | None = None, xsec_source: str | None = None) -> str:
    url = f"https://www.xiaohongshu.com/explore/{note_id}"
    params: list[str] = []
    if xsec_token:
        params.append(f"xsec_token={quote(xsec_token)}")
    if xsec_source:
        params.append(f"xsec_source={quote(xsec_source)}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    return url


def resolve_note_open_url(
    note_id: str,
    *,
    content_url: str | None = None,
    raw_data: dict[str, Any] | None = None,
    note_meta: dict[str, Any] | None = None,
) -> str:
    """从入库笔记信息拼出可直达的笔记链接（优先带 xsec_token）。"""
    note_id = str(note_id or "").strip()
    if not note_id:
        return str(content_url or "").strip()

    token: str | None = None
    source: str | None = None
    candidates: list[str] = []

    for blob in (note_meta, raw_data):
        if not isinstance(blob, dict):
            continue
        for key in ("note_url", "content_url", "video_url"):
            val = str(blob.get(key) or "").strip()
            if val and note_id in val:
                candidates.append(val)
        if not token:
            token = str(blob.get("xsec_token") or "").strip() or None
        if not source:
            source = str(blob.get("xsec_source") or "").strip() or None
        nested = blob.get("raw_data")
        if isinstance(nested, dict):
            if not token:
                token = str(nested.get("xsec_token") or "").strip() or None
            if not source:
                source = str(nested.get("xsec_source") or "").strip() or None

    url_hint = str(content_url or "").strip()
    if url_hint and note_id in url_hint:
        candidates.insert(0, url_hint)

    for url in candidates:
        access = extract_note_access_params(url)
        if access.get("xsec_token"):
            return url

    if token:
        return build_note_url(note_id, token, source or "pc_search")

    for url in candidates:
        return url

    access = extract_note_access_params(url_hint)
    return build_note_url(
        note_id,
        access.get("xsec_token"),
        access.get("xsec_source") or "pc_search",
    )


def to_absolute_url(page_url: str, href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http"):
        return href
    return urljoin(page_url, href)


def walk_note_ids(data: Any) -> list[str]:
    ids: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"note_id", "id", "noteId"} and isinstance(value, str):
                    if re.fullmatch(r"[0-9a-fA-F]{16,32}", value):
                        ids.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    uniq: list[str] = []
    seen: set[str] = set()
    for note_id in ids:
        if note_id in seen:
            continue
        seen.add(note_id)
        uniq.append(note_id)
    return uniq


def find_xsec_in_payload(data: Any) -> tuple[str | None, str | None]:
    """从搜索 API 原始 JSON 递归提取 xsec_token / xsec_source。"""
    token: str | None = None
    source: str | None = None

    def walk(node: Any) -> None:
        nonlocal token, source
        if isinstance(node, dict):
            if not token:
                raw = node.get("xsec_token") or node.get("xsecToken")
                if raw and str(raw).strip():
                    token = str(raw).strip()
            if not source:
                raw = node.get("xsec_source") or node.get("xsecSource")
                if raw and str(raw).strip():
                    source = str(raw).strip()
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return token, source


def parse_note_card(item: dict, *, rank: int, tenant_id: str) -> dict | None:
    card = item.get("note_card") or item.get("note") or item
    if not isinstance(card, dict):
        return None
    # 搜索接口常在 item 顶层放 id/xsec_token，note_card 内未必带 note_id。
    note_id = str(
        card.get("note_id")
        or card.get("id")
        or item.get("note_id")
        or item.get("id")
        or ""
    )
    if not re.fullmatch(r"[0-9a-fA-F]{16,32}", note_id):
        return None
    user = card.get("user") or card.get("author") or {}
    interact = card.get("interact_info") or card.get("interactInfo") or {}
    title = (
        card.get("display_title")
        or card.get("title")
        or card.get("desc")
        or card.get("displayTitle")
        or ""
    )
    title = str(title).strip()
    if not title:
        title = f"小红书笔记 {note_id[:8]}"
    xsec_token = card.get("xsec_token") or item.get("xsec_token")
    xsec_source = card.get("xsec_source") or item.get("xsec_source") or "pc_feed"
    if not xsec_token:
        nested_token, nested_source = find_xsec_in_payload(item)
        xsec_token = xsec_token or nested_token
        xsec_source = xsec_source or nested_source or "pc_feed"
    ip_location = card.get("ip_location") or card.get("ipLocation") or ""
    create_time = card.get("time") or card.get("create_time") or card.get("last_update_time")
    return {
        "platform": "xiaohongshu",
        "rank": rank,
        "title": title[:500],
        "ip_location": str(ip_location).strip(),
        "create_time": create_time,
        "author_name": user.get("nickname") or user.get("nick_name") or user.get("name"),
        "external_id": note_id,
        "video_url": build_note_url(note_id, xsec_token, xsec_source),
        "cover_url": _pick_cover(card),
        "like_count": parse_count(str(interact.get("liked_count") or interact.get("likedCount") or "0")),
        "comment_count": parse_count(str(interact.get("comment_count") or interact.get("commentCount") or "0")),
        "share_count": parse_count(str(interact.get("share_count") or interact.get("sharedCount") or "0")),
        "publish_time": None,
        "author_avatar_url": user.get("avatar"),
        "author_profile_url": None,
        "raw_data": {
            "note_id": note_id,
            "author_id": user.get("user_id") or user.get("userId"),
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
            "tenant_id": tenant_id,
            "platform": "xiaohongshu",
            "card": card,
        },
    }


def _pick_cover(card: dict) -> str | None:
    cover = card.get("cover") or {}
    if isinstance(cover, dict):
        for key in ("url_default", "url", "info_list"):
            value = cover.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict) and first.get("url"):
                    return first["url"]
    image_list = card.get("image_list") or card.get("images") or []
    if image_list and isinstance(image_list[0], dict):
        return image_list[0].get("url") or image_list[0].get("url_default")
    return None


def _normalize_unix_seconds(value: Any) -> int | None:
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    # 小红书评论时间为毫秒，MySQL Integer 列存秒级时间戳。
    if ts > 10_000_000_000:
        ts //= 1000
    return ts


def normalize_xhs_comment(item: dict, parent_comment_id: str | None = None) -> dict:
    user = item.get("user_info") or item.get("user") or {}
    return {
        "comment_id": str(item.get("id") or item.get("comment_id") or ""),
        "parent_comment_id": parent_comment_id,
        "comment": item.get("content") or item.get("text") or "",
        "create_time": _normalize_unix_seconds(item.get("create_time") or item.get("createTime")),
        "digg_count": parse_count(str(item.get("like_count") or item.get("liked_count") or "0")),
        "reply_comment_total": int(item.get("sub_comment_count") or item.get("subCommentCount") or 0),
        "username": user.get("nickname") or user.get("nick_name") or "",
        "user_id": str(user.get("user_id") or user.get("userId") or ""),
        "sec_uid": user.get("xsec_token") or "",
        "avatar": user.get("image") or user.get("avatar") or "",
    }
