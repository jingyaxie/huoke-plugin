from __future__ import annotations

from app.core.config import Settings
from app.platforms.douyin.js_constants import PLATFORM
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore

_JS_REMOVED_HINT = (
    "抖音 JS API 评论回复已移除，请使用 warm_publish 或 human_reply_comment（需浏览器 page）"
)


class DouyinReplyCommentTool:
    """抖音评论回复：已移除 JS comment/publish，请走 warm_publish / human UI。"""

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

    async def reply_comment(self, **_) -> dict:
        raise ValueError(_JS_REMOVED_HINT)
