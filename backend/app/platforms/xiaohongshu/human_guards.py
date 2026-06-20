"""小红书页面人类操作前置检查。"""
from __future__ import annotations

from app.core.config import Settings


class HumanBrowseGuardError(RuntimeError):
    pass


async def assert_xhs_human_ready(
    page,
    settings: Settings,
    *,
    tenant_id: str,
    stage: str = "note",
) -> None:
    url = page.url or ""
    if "xiaohongshu.com" not in url:
        raise HumanBrowseGuardError(f"不在小红书站点（stage={stage}）")
    title = ""
    try:
        title = await page.title()
    except Exception:
        pass
    if "页面不见了" in title or "/404" in url:
        raise HumanBrowseGuardError("笔记或页面不可访问")
