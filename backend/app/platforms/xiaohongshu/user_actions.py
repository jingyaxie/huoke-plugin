from __future__ import annotations

from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.dm import XhsDmTool
from app.platforms.xiaohongshu.profile import build_profile_url
from app.platforms.xiaohongshu.session import XhsSessionStore

__all__ = ["XhsUserActions", "build_profile_url"]

_XHS_WARM_FOLLOW_ERROR = (
    "小红书 Direct API 关注已移除，请使用 warm_outreach（需 comment_id、content_url 与浏览器 page）"
)


class XhsUserActions:
    """组合关注工具与私信工具的门面。"""

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
        self.store = store or XhsSessionStore(settings)
        self._dm = XhsDmTool(settings, tenant_id, self.store, account_id=account_id)

    async def follow_and_dm(
        self,
        *,
        user_id: str,
        username: str = "",
        message: str | None = None,
        follow: bool = True,
        send_message: bool = False,
        show_browser: bool = False,
    ) -> dict:
        result: dict = {
            "platform": "xiaohongshu",
            "tenant_id": self.tenant_id,
            "username": username,
            "user_id": user_id,
            "profile_url": build_profile_url(user_id),
            "follow": None,
            "message": None,
        }
        if follow:
            result["follow"] = {"ok": False, "error": _XHS_WARM_FOLLOW_ERROR}
        if send_message:
            dm_result = await self._dm.send_message(
                user_id=user_id,
                message=message or "",
                username=username,
                show_browser=show_browser,
            )
            result.update(
                {
                    "username": dm_result.get("username") or result.get("username") or username,
                    "message": dm_result.get("message"),
                    "output_file": dm_result.get("output_file") or result.get("output_file"),
                }
            )
        return result
