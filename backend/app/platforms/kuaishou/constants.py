from __future__ import annotations

import re

PLATFORM = "kuaishou"

HOME_URL = "https://www.kuaishou.com"

REQUIRED_LOGIN_COOKIES = frozenset({"userId", "kuaishou.server.web_st"})

SEARCH_FEED_PATH = "/rest/v/search/feed"
PROFILE_GET_PATH = "/rest/v/profile/get"
FOLLOW_PATH = "/rest/v/relation/follow"
GRAPHQL_PATH = "/graphql"

VIDEO_URL_PATTERN = re.compile(r"/short-video/([0-9a-zA-Z_-]+)")
