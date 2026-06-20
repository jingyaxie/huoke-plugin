from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.js_constants import DEFAULT_MAX_COMMENTS, PLATFORM, _extract_aweme_id
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

_JS_REMOVED_HINT = (
    "抖音已移除 JS API 评论抓取，请使用任务模式（ui_first）或 show_browser=true 走侧栏被动抓评"
)


class DouyinCommentTool:
    """抖音视频评论：侧栏 UI + 被动拦截 comment/list（已移除 JS 分页/API 直调）。"""

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

    async def crawl_note_comments(
        self,
        content_url: str,
        show_browser: bool = False,
        *,
        page=None,
        template_url: str | None = None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        days: int | None = None,
        ui_passive: bool = False,
        raw_params: dict | None = None,
        db_session=None,
    ) -> tuple[dict, Path]:
        del template_url  # legacy param, unused
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        aweme_id = _extract_aweme_id(content_url)
        payload = await self._fetch_video_comments(
            video_url=content_url,
            headless=not show_browser,
            page=page,
            max_comments=max_comments,
            days=days,
            raw_params=raw_params,
            db_session=db_session,
        )
        payload["platform"] = PLATFORM
        if payload.get("output_file"):
            return payload, Path(payload["output_file"])
        output = (
            self.settings.report_output_dir
            / f"comments_{self.platform}_{self.tenant_id}_{aweme_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output_file"] = str(output)
        return payload, output

    async def crawl_video_comments(
        self,
        video_url: str,
        show_browser: bool = False,
        **kwargs,
    ) -> tuple[dict, Path]:
        return await self.crawl_note_comments(video_url, show_browser=show_browser, **kwargs)

    async def _fetch_video_comments(
        self,
        video_url: str,
        headless: bool = True,
        *,
        page=None,
        max_comments: int = DEFAULT_MAX_COMMENTS,
        days: int | None = None,
        raw_params: dict | None = None,
        db_session=None,
    ) -> dict:
        from app.platforms.douyin.video_comments_passive import crawl_video_url_comments

        async def _run_ui_passive(target_page) -> dict:
            payload, _meta = await crawl_video_url_comments(
                target_page,
                self.settings,
                tenant_id=self.tenant_id,
                account_id=self.account_id,
                video_url=video_url,
                max_comments=max_comments,
                days=days,
                raw_params=raw_params,
                db_session=db_session,
            )
            return payload

        if page is not None:
            return await _run_ui_passive(page)

        pool = PlaywrightPool.get()
        resolved_headless = headless_for_platform(self.settings, PLATFORM, headless)
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=resolved_headless,
            account_id=self.account_id,
        ) as (_, session_page):
            return await _run_ui_passive(session_page)
