from __future__ import annotations

from app.core.config import Settings
from app.platforms.douyin.js_api import DouyinJsApiTool
from app.platforms.session_store import PlatformSessionStore

PROFILE_PATH = "/aweme/v1/web/user/profile/other/"
PROFILE_SELF_PATH = "/aweme/v1/web/user/profile/self/"
AWEME_POST_PATH = "/aweme/v1/web/aweme/post/"
NOTICE_COUNT_PATH = "/aweme/v1/web/notice/count/"
IM_SPOTLIGHT_PATH = "/aweme/v1/web/im/spotlight/index/"


def build_profile_url(sec_uid: str) -> str:
    return f"https://www.douyin.com/user/{sec_uid}?from_tab_name=main"


def build_im_url(sec_uid: str) -> str:
    return f"https://www.douyin.com/im?secUid={sec_uid}"


class DouyinProfileTool(DouyinJsApiTool):
    """抖音用户主页导航与 profile API。"""

    async def open_profile(self, page, sec_uid: str, *, wait_ms: int = 5000) -> str:
        profile_url = build_profile_url(sec_uid)
        await page.set_viewport_size({"width": 1440, "height": 1200})
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector('[data-e2e="user-detail"]', state="attached", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(wait_ms)
        return profile_url

    async def fetch_profile(self, page, template_url: str, sec_uid: str) -> dict:
        url = self.build_api_url(template_url, PROFILE_PATH, extra={"sec_user_id": sec_uid})
        return await self.fetch_json_via_page(page, url, timeout_ms=12000)

    async def fetch_self_profile(self, page, template_url: str) -> dict:
        url = self.build_api_url(template_url, PROFILE_SELF_PATH)
        return await self.fetch_json_via_page(page, url, timeout_ms=12000)

    async def fetch_self_works(self, page, template_url: str, sec_uid: str, *, limit: int = 10) -> dict:
        url = self.build_api_url(
            template_url,
            AWEME_POST_PATH,
            extra={"sec_user_id": sec_uid, "max_cursor": "0", "count": str(limit)},
        )
        return await self.fetch_json_via_page(page, url, timeout_ms=12000)

    async def fetch_notice_count(self, page, template_url: str) -> dict:
        url = self.build_api_url(template_url, NOTICE_COUNT_PATH)
        return await self.fetch_json_via_page(page, url, timeout_ms=12000)

    async def fetch_im_spotlight(self, page, template_url: str) -> dict:
        url = self.build_api_url(template_url, IM_SPOTLIGHT_PATH)
        return await self.fetch_json_via_page(page, url, timeout_ms=12000)
