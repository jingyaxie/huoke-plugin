from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.crawl_cache import CacheMeta, CrawlCacheOptions


class AccountDashboardRequest(CrawlCacheOptions):
    show_browser: bool = Field(default=False, description="是否使用可见浏览器（调试用）")
    works_limit: int = Field(default=10, ge=1, le=50, description="作品/笔记返回数量上限")


class AccountDashboardResponse(BaseModel):
    ok: bool
    platform: str
    tenant_id: str
    account_id: str
    tool: str = "account_dashboard"
    data: dict
    diagnostic: Optional[str] = None
    report_file: Optional[str] = None
    cache: CacheMeta | None = None
