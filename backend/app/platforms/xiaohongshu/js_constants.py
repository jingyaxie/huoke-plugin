from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.platforms.xiaohongshu.constants import (
    COMMENT_PAGE_PATH,
    COMMENT_SUB_PATH,
    HOMEFEED_PATH,
    PLATFORM,
    SEARCH_NOTES_PATH,
)

EDITH_HOST = "edith.xiaohongshu.com"
FOLLOW_PATH = "/api/sns/web/v1/user/follow"
UNFOLLOW_PATH = "/api/sns/web/v1/user/unfollow"
COMMENT_POST_PATH = "/api/sns/web/v1/comment/post"
USER_OTHERINFO_PATH = "/api/sns/web/v1/user/otherinfo"

DEFAULT_MAX_COMMENTS = 200
DROP_QUERY_KEYS = {"x-s", "x-t", "x-s-common"}

_SEARCH_API_EXCLUDES = ("login/qrcode", "suggest", "recommend")
_API_TEMPLATE_MARKERS = (
    SEARCH_NOTES_PATH,
    "/api/sns/web/v2/search/notes",
    HOMEFEED_PATH,
    COMMENT_PAGE_PATH,
    USER_OTHERINFO_PATH,
)
_API_TEMPLATE_EXCLUDES = (
    "login/",
    "qrcode",
    COMMENT_SUB_PATH,
    "/sec/",
)

_FIRE_FETCH_JS = """async ({ url, timeoutMs }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        await fetch(url, { credentials: 'include', signal: controller.signal });
    } catch {
    } finally {
        clearTimeout(timer);
    }
}"""


def _encode_search_keyword(keyword: str) -> str:
    return quote(keyword.strip())


def _build_search_url(keyword: str) -> str:
    """已废弃：小红书搜索须走探索页搜索框，禁止拼接 search_result URL 直跳。"""
    return (
        f"https://www.xiaohongshu.com/search_result"
        f"?keyword={_encode_search_keyword(keyword)}&source=web_search_result_notes"
    )


def _build_comment_page_url(
    template_url: str,
    note_id: str,
    *,
    cursor: str = "",
    xsec_token: str | None = None,
    xsec_source: str | None = None,
) -> str:
    split = urlsplit(template_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update({"note_id": note_id, "cursor": cursor, "top_comment_id": "", "image_formats": "jpg,webp,avif"})
    if xsec_token:
        query["xsec_token"] = xsec_token
    if xsec_source:
        query["xsec_source"] = xsec_source
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit(
        (
            split.scheme or "https",
            split.netloc or EDITH_HOST,
            COMMENT_PAGE_PATH,
            urlencode(query, doseq=True),
            "",
        )
    )


def _build_follow_url() -> str:
    return f"https://{EDITH_HOST}{FOLLOW_PATH}"


def _build_unfollow_url() -> str:
    return f"https://{EDITH_HOST}{UNFOLLOW_PATH}"


def _build_comment_post_url() -> str:
    return f"https://{EDITH_HOST}{COMMENT_POST_PATH}"


def _build_user_otherinfo_url(template_url: str, user_id: str) -> str:
    split = urlsplit(template_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query["target_user_id"] = user_id
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit(
        (
            split.scheme or "https",
            split.netloc or EDITH_HOST,
            USER_OTHERINFO_PATH,
            urlencode(query, doseq=True),
            "",
        )
    )


def _is_search_result_api(url: str) -> bool:
    if any(ex in url for ex in _SEARCH_API_EXCLUDES):
        return False
    if "xiaohongshu.com" not in url:
        return False
    return "/search/notes" in url
