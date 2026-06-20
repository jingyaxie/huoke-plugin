from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_constants import PLATFORM
from app.platforms.xiaohongshu.profile import build_profile_url
from app.platforms.xiaohongshu.session import XhsSessionStore

_PC_DM_UNSUPPORTED_HINT = (
    "小红书 PC 网页版不提供用户私信能力（主页无发消息入口，/im 路由不可用）。"
    "请使用抖音/快手，或通过小红书 App 手动私信。"
)


class XhsDmTool:
    """小红书私信工具：PC 网页端不支持私信，接口直接返回明确说明。"""

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
        self.store = store or XhsSessionStore(settings)

    async def send_message(
        self,
        *,
        user_id: str,
        message: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        if not user_id:
            raise ValueError("缺少 user_id")
        if not (message or "").strip():
            raise ValueError("发送私信需要 message")

        result = {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "username": username,
            "user_id": user_id,
            "profile_url": build_profile_url(user_id),
            "capture_method": "unsupported_pc_web",
            "message": {
                "ok": False,
                "error": "platform_unsupported",
                "hint": _PC_DM_UNSUPPORTED_HINT,
            },
        }
        output = (
            self.settings.report_output_dir
            / f"dm_{self.platform}_{self.tenant_id}_{user_id[:12]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result
