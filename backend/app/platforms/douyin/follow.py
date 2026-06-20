from __future__ import annotations

from app.core.config import Settings
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore

PLATFORM = "douyin"

_JS_REMOVED_HINT = (
    "抖音 JS API 关注/取关已移除，请使用 warm_outreach 或 human_follow_user（需浏览器 page）"
)


def _is_followed_status(follow_status: int) -> bool:
    """follow_status: 0=未关注, 1=已关注, 2=互相关注"""
    return int(follow_status or 0) in {1, 2}


class DouyinFollowTool:
    """抖音关注/取关：已移除 JS POST，请走 warm_outreach / human UI。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.platform = PLATFORM
        self.store = store or DouyinSessionStore(settings)

    async def follow_user(self, **_) -> dict:
        raise ValueError(_JS_REMOVED_HINT)

    async def unfollow_user(self, **_) -> dict:
        raise ValueError(_JS_REMOVED_HINT)
