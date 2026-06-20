from __future__ import annotations

import re
from typing import Protocol

from app.platforms.constants import DEFAULT_PLATFORM, SUPPORTED_PLATFORMS
from app.schemas.crawl import CrawlItem


_PLATFORM_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def normalize_platform(platform: str | None) -> str:
    value = (platform or DEFAULT_PLATFORM).strip().lower()
    if not _PLATFORM_PATTERN.fullmatch(value):
        raise ValueError("platform 仅允许小写字母、数字、下划线、连字符，且长度 1-32")
    if value not in SUPPORTED_PLATFORMS:
        raise ValueError(f"暂不支持的平台: {value}，当前可用: {', '.join(sorted(SUPPORTED_PLATFORMS))}")
    return value


def platform_from_content_url(url: str | None) -> str | None:
    """从视频/笔记链接推断平台；无法识别时返回 None。"""
    if not url:
        return None
    lower = url.strip().lower()
    if "kuaishou.com" in lower or "gifshow.com" in lower or "chenzhongtech.com" in lower:
        return "kuaishou"
    if "xiaohongshu.com" in lower or "xhslink.com" in lower:
        return "xiaohongshu"
    if "douyin.com" in lower or "iesdouyin.com" in lower:
        return "douyin"
    return None


class PlatformHotCrawler(Protocol):
    platform: str

    async def login_and_save_cookies(self, show_browser: bool = True) -> None: ...

    async def start_interactive_login_session(self) -> dict: ...

    async def fetch_hot(self, limit: int = 100) -> list[CrawlItem]: ...

    def login_status(self, tenant_id: str) -> dict: ...

    @classmethod
    def get_interactive_session(cls, platform: str, tenant_id: str) -> dict | None: ...
