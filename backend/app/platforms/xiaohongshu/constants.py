from __future__ import annotations

import re

from app.core.antibot import DEFAULT_USER_AGENT

PLATFORM = "xiaohongshu"

REQUIRED_LOGIN_COOKIES = {"web_session", "a1", "webId"}

HOMEFEED_PATH = "/api/sns/web/v1/homefeed"
SEARCH_NOTES_PATH = "/api/sns/web/v1/search/notes"
COMMENT_PAGE_PATH = "/api/sns/web/v2/comment/page"
COMMENT_SUB_PATH = "/api/sns/web/v2/comment/sub/page"

NOTE_URL_PATTERN = re.compile(
    r"(?:/explore/|/discovery/item/|/note/)([0-9a-fA-F]{16,32})"
)

_LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
USER_AGENT = DEFAULT_USER_AGENT
