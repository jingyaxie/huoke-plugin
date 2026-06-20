from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.platforms.registry import get_account_dashboard_tool
from app.platforms.types import normalize_platform
from app.schemas.crawl_cache import DEFAULT_CACHE_TTL_HOURS, CacheMeta
from app.services.cached_crawl_coordinator import CachedCrawlCoordinator


class AccountDashboardService:
    """已登录账号主页监控服务（跨平台统一入口）。"""

    def __init__(
        self,
        settings: Settings | None = None,
        tenant_id: str | None = None,
        account_id: str = "default",
        session: Session | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tenant_id = tenant_id or self.settings.default_tenant_id
        self.account_id = account_id
        self.session = session

    async def fetch_dashboard(
        self,
        platform: str,
        *,
        show_browser: bool = False,
        works_limit: int = 10,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> tuple[dict, Path, CacheMeta | None]:
        platform = normalize_platform(platform)
        tool = get_account_dashboard_tool(self.settings, platform, self.tenant_id, account_id=self.account_id)
        if self.session is not None:
            coordinator = CachedCrawlCoordinator(
                self.session,
                self.settings,
                tenant_id=self.tenant_id,
                platform=platform,
                account_id=self.account_id,
            )
            result = await coordinator.cached_dashboard(
                tool.fetch_dashboard,
                show_browser=show_browser,
                works_limit=works_limit,
                force_refresh=force_refresh,
                cache_ttl_hours=cache_ttl_hours,
            )
            return result.payload, result.output or Path(""), result.meta
        payload, output = await tool.fetch_dashboard(show_browser=show_browser, works_limit=works_limit)
        return payload, output, None
