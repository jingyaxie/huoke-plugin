from __future__ import annotations

import json

from app.platforms.kuaishou.constants import (
    FOLLOW_PATH,
    GRAPHQL_PATH,
    PLATFORM,
    PROFILE_GET_PATH,
    SEARCH_FEED_PATH,
)

DEFAULT_MAX_COMMENTS = 200
DROP_QUERY_KEYS = {"__NS_hxfalcon", "__NS_sig3", "sig"}

_SEARCH_API_MARKERS = (SEARCH_FEED_PATH,)
_SEARCH_API_EXCLUDES = ("search/user", "search/suggest")
_API_TEMPLATE_MARKERS = (
    SEARCH_FEED_PATH,
    PROFILE_GET_PATH,
    GRAPHQL_PATH,
)
_API_TEMPLATE_EXCLUDES = (
    "login/",
    "passToken",
    "/infra/",
)

COMMENT_LIST_OPERATION = "commentListQuery"
COMMENT_ADD_OPERATION = "visionAddComment"
VIDEO_DETAIL_OPERATION = "visionVideoDetail"
VIDEO_DETAIL_QUERY = """query visionVideoDetail($photoId: String) {
  visionVideoDetail(photoId: $photoId) {
    llsid
    author {
      id
      name
      __typename
    }
    photo {
      id
      expTag
      caption
      __typename
    }
    commentLimit {
      canAddComment
      __typename
    }
    __typename
  }
}"""
COMMENT_LIST_QUERY = """query commentListQuery($photoId: String, $pcursor: String) {
  visionCommentList(photoId: $photoId, pcursor: $pcursor) {
    commentCount
    commentCountV2
    pcursor
    rootCommentsV2 {
      commentId
      authorId
      authorName
      content
      headurl
      timestamp
      likedCount
      hasSubComments
      status
    }
  }
}"""

COMMENT_ADD_MUTATION = """mutation visionAddComment($photoId: String, $photoAuthorId: String, $content: String, $replyToCommentId: ID, $replyTo: ID, $expTag: String) {
  visionAddComment(photoId: $photoId, photoAuthorId: $photoAuthorId, content: $content, replyToCommentId: $replyToCommentId, replyTo: $replyTo, expTag: $expTag) {
    result
    commentId
    content
    timestamp
    status
    __typename
  }
}"""

_FIRE_FETCH_JS = """async ({ url, body, timeoutMs }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body,
            signal: controller.signal,
        });
    } catch {
    } finally {
        clearTimeout(timer);
    }
}"""


def _build_search_feed_body(keyword: str, *, pcursor: str = "") -> str:
    return json.dumps(
        {
            "keyword": keyword,
            "page": "search",
            "webPageArea": "",
            "pcursor": pcursor,
        },
        ensure_ascii=False,
    )


def _build_follow_body(user_id: str) -> str:
    return json.dumps({"touid": user_id, "ftype": 1}, ensure_ascii=False)


def _build_unfollow_body(user_id: str) -> str:
    return json.dumps({"touid": user_id, "ftype": 2}, ensure_ascii=False)


def _is_search_result_api(url: str) -> bool:
    if any(ex in url for ex in _SEARCH_API_EXCLUDES):
        return False
    return SEARCH_FEED_PATH in url


def _is_comment_graphql_request(post_data: str | None) -> bool:
    return bool(post_data and COMMENT_LIST_OPERATION in post_data)
