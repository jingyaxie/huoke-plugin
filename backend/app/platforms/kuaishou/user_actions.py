from __future__ import annotations

from app.core.config import Settings
from app.platforms.kuaishou.dm import KuaishouDmTool
from app.platforms.kuaishou.follow import KuaishouFollowTool
from app.platforms.kuaishou.session import KuaishouSessionStore
from app.platforms.kuaishou.utils import build_profile_url
from app.platforms.session_store import PlatformSessionStore

__all__ = ["KuaishouUserActions", "build_profile_url"]


class KuaishouUserActions:
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
        self.store = store or KuaishouSessionStore(settings)
        self._follow = KuaishouFollowTool(settings, tenant_id, self.store, account_id=account_id)
        self._dm = KuaishouDmTool(settings, tenant_id, self.store, account_id=account_id)

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
            "platform": "kuaishou",
            "tenant_id": self.tenant_id,
            "username": username,
            "user_id": user_id,
            "profile_url": build_profile_url(user_id),
            "follow": None,
            "message": None,
        }
        if follow:
            follow_result = await self._follow.follow_user(
                user_id=user_id,
                username=username,
                show_browser=show_browser,
            )
            result.update(
                {
                    "username": follow_result.get("username") or username,
                    "follow_status_before": follow_result.get("follow_status_before"),
                    "follow_status_after": follow_result.get("follow_status_after"),
                    "follow": follow_result.get("follow"),
                    "output_file": follow_result.get("output_file"),
                }
            )
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
