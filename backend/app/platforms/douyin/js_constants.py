from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PLATFORM = "douyin"

_SEARCH_RESULT_API_MARKERS = ("general/search/single", "search/item", "search/single")
_SEARCH_API_EXCLUDES = ("hot/search", "search/sug", "suggest_words", "api/suggest")

COMMENT_PATH = "/aweme/v1/web/comment/list"
REPLY_COMMENT_PATH = "/aweme/v1/web/comment/list/reply"
COMMENT_PUBLISH_PATH = "/aweme/v1/web/comment/publish/"
SEARCH_SINGLE_PATH = "/aweme/v1/web/general/search/single/"
SEARCH_ITEM_PATH = "/aweme/v1/web/search/item/"
DROP_QUERY_KEYS = {"a_bogus", "x-secsdk-web-signature", "msToken"}
DEFAULT_MAX_COMMENTS = 200
_API_TEMPLATE_MARKERS = (
    "suggest_words",
    "search/sug",
    "general/search",
    "search/single",
    "search/item",
    "hot/search",
)
_API_TEMPLATE_EXCLUDES = (
    "hot/search/list",
    "comment/list",
    "solution/resource",
    "abtest",
    "/status",
    "/settings",
    "relation/",
    "/carnival",
    "/info/",
)
_SEARCH_JS_CHANNELS = (
    (SEARCH_SINGLE_PATH, "aweme_video_web"),
    (SEARCH_SINGLE_PATH, "aweme_general"),
    (SEARCH_ITEM_PATH, "aweme_video_web"),
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


def _extract_aweme_id(video_url: str) -> str:
    url = (video_url or "").strip()
    if not url:
        raise ValueError(f"无法从链接解析 aweme_id: {video_url}")
    match = re.search(r"/(?:video|note)/(\d+)", url)
    if match:
        return match.group(1)
    for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if key == "modal_id" and str(value).isdigit():
            return str(value)
    raise ValueError(f"无法从链接解析 aweme_id: {video_url}")


def _try_extract_aweme_id(video_url: str) -> str:
    try:
        return _extract_aweme_id(video_url)
    except ValueError:
        return ""


def _normalize_comment(item: dict, parent_comment_id: str | None = None) -> dict:
    user = item.get("user") or {}
    avatar = user.get("avatar_larger") or user.get("avatar_medium") or user.get("avatar_thumb") or {}
    avatar_url_list = avatar.get("url_list") or []
    return {
        "comment_id": str(item.get("cid") or ""),
        "parent_comment_id": parent_comment_id,
        "comment": item.get("text") or "",
        "create_time": item.get("create_time"),
        "digg_count": int(item.get("digg_count") or 0),
        "reply_comment_total": int(item.get("reply_comment_total") or 0),
        "username": user.get("nickname") or "",
        "user_id": str(user.get("uid") or ""),
        "sec_uid": user.get("sec_uid") or "",
        "avatar": avatar_url_list[0] if avatar_url_list else "",
    }


def _build_next_url(base_url: str, cursor: int) -> str:
    split = urlsplit(base_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query["cursor"] = str(cursor)
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query, doseq=True), ""))


def _build_search_sug_url(template_url: str, keyword: str) -> str:
    split = urlsplit(template_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update({"keyword": keyword, "source": "aweme_video_web"})
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit(
        (
            split.scheme or "https",
            split.netloc or "www.douyin.com",
            "/aweme/v1/web/search/sug/",
            urlencode(query, doseq=True),
            "",
        )
    )


def _extract_search_id_from_sug(data: dict) -> str | None:
    record = data.get("words_query_record")
    if isinstance(record, dict):
        for key in ("search_id", "impr_id", "query_id"):
            value = record.get(key)
            if value:
                return str(value)
    extra = data.get("extra")
    if isinstance(extra, dict):
        for key in ("search_id", "impr_id", "search_request_id"):
            value = extra.get(key)
            if value:
                return str(value)
    return None


def _encode_search_keyword(keyword: str) -> str:
    from urllib.parse import quote
    return quote(keyword.strip())


def _build_search_api_url(
    template_url: str,
    keyword: str,
    *,
    path: str = SEARCH_SINGLE_PATH,
    offset: int = 0,
    count: int = 10,
    search_channel: str = "aweme_video_web",
    search_id: str | None = None,
    days: int | None = None,
) -> str:
    from app.platforms.search_filters import douyin_filter_selected_json

    split = urlsplit(template_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    filter_json = douyin_filter_selected_json(days)
    query.update(
        {
            "keyword": keyword,
            "offset": str(offset),
            "count": str(count),
            "search_source": "tab_search" if filter_json else "normal_search",
            "query_correct_type": "1",
            "is_filter_search": "1" if filter_json else "0",
            "search_channel": search_channel,
            "enable_history": "1",
            "list_type": "single",
            "need_filter_settings": "1" if filter_json else "0",
        }
    )
    if filter_json:
        query["filter_selected"] = filter_json
    else:
        query.pop("filter_selected", None)
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    if search_id:
        query["search_id"] = search_id
    else:
        query.pop("search_id", None)
    return urlunsplit(
        (
            split.scheme or "https",
            split.netloc or "www.douyin.com",
            path,
            urlencode(query, doseq=True),
            "",
        )
    )


def _build_comment_list_url(template_url: str, aweme_id: str, *, cursor: int = 0, count: int = 20) -> str:
    split = urlsplit(template_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update(
        {
            "aweme_id": aweme_id,
            "item_id": aweme_id,
            "cursor": str(cursor),
            "count": str(count),
        }
    )
    for key in DROP_QUERY_KEYS:
        query.pop(key, None)
    return urlunsplit(
        (
            split.scheme or "https",
            split.netloc or "www.douyin.com",
            COMMENT_PATH,
            urlencode(query, doseq=True),
            "",
        )
    )
