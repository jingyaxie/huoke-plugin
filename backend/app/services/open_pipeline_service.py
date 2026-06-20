from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.open_pipeline import (
    KeywordVideoCommentsRequest,
    KeywordVideoCommentsResponse,
    PlatformPipelineResult,
)
from app.services.agent_async_job_service import AgentAsyncJobService
from app.services.cached_crawl_coordinator import CachedCrawlCoordinator
from app.services.skill_runner_service import SkillRunnerService


def _pipeline_skill_args(req: KeywordVideoCommentsRequest) -> str:
    parts = [f"keyword={req.keyword}", f"video_limit={req.video_limit}", f"days={req.days}"]
    if req.video_publish_days is not None:
        parts.append(f"video_publish_days={req.video_publish_days}")
    if req.region:
        parts.append(f"region={req.region}")
    if req.headless is not None:
        parts.append(f"headless={str(req.headless).lower()}")
        if req.headless is False:
            parts.append("show_browser=true")
    if req.force_refresh:
        parts.append("force_refresh=true")
    return " ".join(parts)


class OpenPipelineService:
    """对外 Pipeline：经 SkillRunner 执行 keyword-comments 抓取。"""

    def __init__(self, settings: Settings, tenant_id: str, db_session: Session | None = None) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.db_session = db_session

    async def run_keyword_video_comments(
        self,
        req: KeywordVideoCommentsRequest,
        *,
        account_id: str = "default",
    ) -> KeywordVideoCommentsResponse:
        if req.async_job:
            return await self._submit_async(req, account_id=account_id)

        if self.db_session is not None and not req.force_refresh:
            coordinator = CachedCrawlCoordinator(
                self.db_session,
                self.settings,
                tenant_id=self.tenant_id,
                platform="pipeline",
                account_id=account_id,
            )
            cached = coordinator.cached_pipeline_lookup(
                keyword=req.keyword,
                platforms=list(req.platforms),
                video_limit=req.video_limit,
                days=req.days,
                video_publish_days=req.video_publish_days,
                region=req.region,
                force_refresh=req.force_refresh,
                cache_ttl_hours=req.cache_ttl_hours,
            )
            if cached is not None:
                payload = cached.payload
                return KeywordVideoCommentsResponse(
                    keyword=req.keyword,
                    status=str(payload.get("status") or "completed"),
                    platforms=[
                        PlatformPipelineResult(**item)
                        for item in (payload.get("platforms") or [])
                        if isinstance(item, dict)
                    ],
                    completed_at=datetime.now(timezone.utc),
                )

        platform_results: list[PlatformPipelineResult] = []
        overall_ok = True
        for platform in req.platforms:
            item = await self._run_single_platform(req, platform, account_id=account_id)
            platform_results.append(item)
            if item.status != "completed":
                overall_ok = False

        response = KeywordVideoCommentsResponse(
            keyword=req.keyword,
            status="completed" if overall_ok else "partial",
            platforms=platform_results,
            completed_at=datetime.now(timezone.utc),
        )
        if self.db_session is not None:
            coordinator = CachedCrawlCoordinator(
                self.db_session,
                self.settings,
                tenant_id=self.tenant_id,
                platform="pipeline",
                account_id=account_id,
            )
            if overall_ok:
                coordinator.store_pipeline_result(
                    keyword=req.keyword,
                    platforms=list(req.platforms),
                    video_limit=req.video_limit,
                    days=req.days,
                    video_publish_days=req.video_publish_days,
                    region=req.region,
                    payload=response.model_dump(mode="json"),
                    cache_ttl_hours=req.cache_ttl_hours,
                )
            elif req.force_refresh:
                fallback = self._pipeline_stale_fallback(coordinator, req, account_id=account_id)
                if fallback is not None:
                    return fallback
        return response

    def _pipeline_stale_fallback(
        self,
        coordinator: CachedCrawlCoordinator,
        req: KeywordVideoCommentsRequest,
        *,
        account_id: str,
    ) -> KeywordVideoCommentsResponse | None:
        params = {
            "keyword": req.keyword,
            "platforms": list(req.platforms),
            "video_limit": req.video_limit,
            "days": req.days,
            "video_publish_days": req.video_publish_days,
            "region": req.region,
        }
        stale = coordinator.cache.lookup_stale("pipeline_keyword_comments", params)
        if stale is None:
            return None
        payload = stale.payload
        meta = stale.meta.model_copy(
            update={"stale_fallback": True, "refresh_error": "强制拉取未成功，已回退缓存"},
        )
        return KeywordVideoCommentsResponse(
            keyword=req.keyword,
            status=str(payload.get("status") or "completed"),
            platforms=[
                PlatformPipelineResult(**item)
                for item in (payload.get("platforms") or [])
                if isinstance(item, dict)
            ],
            completed_at=datetime.now(timezone.utc),
            cache=meta,
        )

    async def _run_single_platform(
        self,
        req: KeywordVideoCommentsRequest,
        platform: str,
        *,
        account_id: str,
    ) -> PlatformPipelineResult:
        runner = SkillRunnerService(
            self.settings,
            self.tenant_id,
            platform,
            account_id=account_id,
            db_session=self.db_session,
        )
        try:
            return await asyncio.wait_for(
                runner.run_open_pipeline_platform(req),
                timeout=req.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return PlatformPipelineResult(
                platform=platform,
                status="failed",
                error=f"执行超时（>{req.timeout_seconds}s）",
            )
        except Exception as exc:
            return PlatformPipelineResult(
                platform=platform,
                status="failed",
                error=str(exc),
            )

    async def _submit_async(
        self,
        req: KeywordVideoCommentsRequest,
        *,
        account_id: str,
    ) -> KeywordVideoCommentsResponse:
        platform = req.platforms[0] if req.platforms else "douyin"
        message = (
            f"/douyin-keyword-comments {_pipeline_skill_args(req)}\n"
            "请使用类人分步 Skill 执行，最终在 task_complete.result 返回结构化 JSON。"
        )
        job = await AgentAsyncJobService.get(self.settings).submit_async(
            tenant_id=self.tenant_id,
            platform=platform,
            account_id=account_id,
            message=message,
            provider=req.provider,
            timeout_seconds=req.timeout_seconds,
            priority=3,
        )
        return KeywordVideoCommentsResponse(
            keyword=req.keyword,
            status="queued",
            job_id=job.job_id,
            platforms=[
                PlatformPipelineResult(platform=platform, status="queued", summary="已提交异步任务")
            ],
        )
