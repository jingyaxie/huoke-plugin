from __future__ import annotations

import json

from app.platforms.kuaishou.constants import PROFILE_GET_PATH
from app.platforms.kuaishou.js_api import KuaishouJsApiTool
from app.platforms.kuaishou.utils import build_profile_url

PROFILE_PHOTO_LIST_QUERY = """query visionProfilePhotoList($userId: String, $pcursor: String, $page: String) {
  visionProfilePhotoList(userId: $userId, pcursor: $pcursor, page: $page) {
    feeds {
      type
      photo {
        id
        caption
        timestamp
        viewCount
        likeCount
        commentCount
      }
    }
    pcursor
  }
}"""


class KuaishouProfileTool(KuaishouJsApiTool):
    """快手用户主页导航与 profile API。"""

    async def open_profile(self, page, user_id: str, *, wait_ms: int = 5000) -> str:
        profile_url = build_profile_url(user_id)
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(wait_ms)
        return profile_url

    async def fetch_user_profile(self, page, template_url: str, user_id: str) -> dict:
        url = self.build_api_url(template_url, PROFILE_GET_PATH)
        body = json.dumps({"user_id": user_id}, ensure_ascii=False)
        return await self.post_json_via_page(page, url, body, timeout_ms=12000)

    async def fetch_user_works(self, page, user_id: str, *, limit: int = 10) -> dict:
        return await self.graphql_via_page(
            page,
            operation_name="visionProfilePhotoList",
            query=PROFILE_PHOTO_LIST_QUERY,
            variables={"userId": user_id, "pcursor": "", "page": "profile"},
            timeout_ms=15000,
        )
