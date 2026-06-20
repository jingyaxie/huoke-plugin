from __future__ import annotations

import asyncio

from app.core.config import Settings, get_settings
from app.platforms.qr_login_parsers import expires_in_seconds, utc_iso
from app.platforms.qr_login_store import (
    QrLoginSession,
    create_session,
    get_session,
    remove_session,
)
from app.platforms.registry import get_qr_login_tool, get_session_store
from app.platforms.types import normalize_platform


class QrLoginService:
    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.account_id = account_id

    async def create_qr_login(self, platform: str, *, refresh: bool = True) -> QrLoginSession:
        platform = normalize_platform(platform)
        tool = get_qr_login_tool(self.settings, platform, self.tenant_id, account_id=self.account_id)

        if refresh:
            await self._cancel_active(platform)

        session = create_session(platform, self.tenant_id, self.account_id)
        runtime = await tool.open_runtime()
        session.runtime = runtime
        try:
            await tool.fetch_qr(session, runtime)
        except Exception:
            await tool.cleanup_runtime(runtime)
            remove_session(session.session_id)
            raise
        await tool.start_poll_loop(session)
        return session

    async def get_status(self, platform: str, session_id: str) -> QrLoginSession:
        platform = normalize_platform(platform)
        session = get_session(session_id)
        if session is None:
            raise KeyError("二维码登录会话不存在或已结束")
        if session.platform != platform or session.tenant_id != self.tenant_id or session.account_id != self.account_id:
            raise PermissionError("无权访问该二维码登录会话")
        return session

    async def cancel(self, platform: str, session_id: str) -> bool:
        platform = normalize_platform(platform)
        session = await self.get_status(platform, session_id)
        return await self._cancel_session(session)

    async def _cancel_active(self, platform: str) -> None:
        from app.platforms.qr_login_store import get_active_session

        active = get_active_session(platform, self.tenant_id, self.account_id)
        if active is not None:
            await self._cancel_session(active)

    async def _cancel_session(self, session: QrLoginSession) -> bool:
        task = session.poll_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        tool = get_qr_login_tool(self.settings, session.platform, session.tenant_id, account_id=session.account_id)
        await tool.cleanup_runtime(session.runtime)
        session.runtime = {}
        session.status = "cancelled"
        session.message = "二维码登录已取消"
        remove_session(session.session_id)
        return True

    def session_payload(self, session: QrLoginSession, *, include_login: bool = False) -> dict:
        store = get_session_store(self.settings, session.platform)
        login_ready = session.status == "confirmed"
        payload = {
            "ok": session.status not in {"error", "expired", "cancelled"},
            "platform": session.platform,
            "tenant_id": session.tenant_id,
            "account_id": session.account_id,
            "session_id": session.session_id,
            "status": session.status,
            "qr_image_url": session.qr_image_url,
            "qr_image_base64": session.qr_image_base64,
            "qr_scan_url": session.qr_scan_url,
            "expires_at": utc_iso(session.expires_at),
            "expires_in_seconds": expires_in_seconds(session.expires_at),
            "validity_hint": session.validity_hint,
            "poll_interval_seconds": 2,
            "message": session.message,
            "login_ready": login_ready,
        }
        if include_login and login_ready:
            payload["login_status"] = store.login_status(self.tenant_id, self.account_id)
        return payload
