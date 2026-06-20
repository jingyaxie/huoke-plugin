from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.open_pipeline import KeywordVideoCommentsRequest, PlatformPipelineResult
from app.schemas.skill import SkillOut
from app.services.agent_browser_session import AgentBrowserSession, AgentSessionManager
from app.services.agent_service import AgentService
from app.services.playwright_tools import PlaywrightToolExecutor
from app.services.skill_executor import SkillExecutor
from app.services.platform_skill_map import keyword_skill_for_platform
from app.services.skill_store import SkillStore

DEFAULT_CRAWL_VIDEO_LIMIT = 5


def _crawl_video_limit(params: dict[str, Any], *, default: int = DEFAULT_CRAWL_VIDEO_LIMIT) -> int:
    for key in ("crawl_video_limit", "video_limit", "content_limit", "limit", "video_limit_per_batch"):
        val = params.get(key)
        if val is None or val == "":
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return default


def _is_success(result: dict[str, Any]) -> bool:
    if result.get("error"):
        return False
    status = str(result.get("status") or "").lower()
    if status in {"failed", "error"}:
        return False
    if status == "completed":
        return True
    if result.get("handler") and not result.get("error"):
        return True
    return bool(result.get("results") or result.get("videos_processed"))


def _normalize_execute_result(result: dict[str, Any], *, skill_id: str) -> dict[str, Any]:
    if result.get("error") and not result.get("status"):
        result = {**result, "status": "failed"}
    if _is_success(result) and not result.get("status"):
        result = {**result, "status": "completed"}
    result.setdefault("skill_id", skill_id)
    return result


class SkillRunnerService:
    """统一 Skill 执行入口：REST / Pipeline / Agent 共用。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        platform: str,
        *,
        account_id: str = "default",
        db_session: Session | None = None,
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.account_id = account_id
        self.db_session = db_session
        self._store = SkillStore(settings)

    def get_skill(self, skill_id: str) -> SkillOut | None:
        return self._store.get(self.tenant_id, skill_id)

    async def execute(
        self,
        skill_id: str,
        params: dict[str, Any] | None = None,
        *,
        headless: bool | None = None,
        agent_fallback: bool = False,
        provider: str = "deepseek",
        timeout_seconds: int = 600,
        browser_session: AgentBrowserSession | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        skill = self.get_skill(skill_id)
        if skill is None:
            return {"status": "failed", "error": f"技能不存在: {skill_id}", "skill_id": skill_id}

        if skill.builtin_handler == "pipeline_keyword_comments":
            return await self.execute_keyword_pipeline(
                keyword=str(params.get("keyword") or ""),
                video_limit=_crawl_video_limit(params),
                days=int(params.get("days") or 3),
                region=params.get("region"),
                headless=headless,
                agent_fallback=agent_fallback or bool(params.get("agent_fallback", True)),
                provider=provider,
                timeout_seconds=timeout_seconds,
                force_refresh=bool(params.get("force_refresh", False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
                guest_mode=bool(params.get("guest_mode", False)),
            )

        if skill.type == "instruction" and not agent_fallback:
            return {
                "status": "failed",
                "error": "instruction 技能需在 Agent 对话中执行，或设置 agent_fallback=true",
                "skill_id": skill_id,
                "type": "instruction",
            }

        if skill.type == "instruction" and agent_fallback:
            return await self._run_recovery_agent(
                task=self._build_instruction_task(skill, params),
                provider=provider,
                timeout_seconds=timeout_seconds,
                explicit_skill_ids=[skill_id],
            )

        result = await self._execute_skill_direct(
            skill,
            params,
            headless=headless,
            session=browser_session,
            timeout_seconds=timeout_seconds if skill.builtin_handler in {
                "crawl_keyword_comments",
                "crawl_profile_comments",
                "search_videos",
                "collect_profile_videos",
                "crawl_video_comments",
            } else None,
        )
        return _normalize_execute_result(result, skill_id=skill_id)

    async def _execute_skill_direct(
        self,
        skill: SkillOut,
        params: dict[str, Any],
        *,
        headless: bool | None,
        session: AgentBrowserSession | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        owns_session = session is None
        if owns_session:
            session = await self._borrow_session(headless=headless)
        if owns_session or not session.is_started:
            await session.ensure_started()
        pw_executor = PlaywrightToolExecutor(session, self.settings)
        executor = SkillExecutor(
            self.settings,
            self.tenant_id,
            self.platform,
            session,
            pw_executor,
            db_session=self.db_session,
        )
        try:
            if timeout_seconds and timeout_seconds > 0:
                return await asyncio.wait_for(
                    executor.execute(skill, params),
                    timeout=float(timeout_seconds),
                )
            return await executor.execute(skill, params)
        except asyncio.TimeoutError:
            try:
                from app.services.playwright_pool import PlaywrightPool

                await PlaywrightPool.get().shutdown()
            except Exception:
                pass
            return {
                "error": f"技能执行超时（>{timeout_seconds}s）",
                "status": "failed",
                "skill_id": skill.id,
            }
        finally:
            if owns_session:
                await self._release_session(session)

    async def execute_keyword_pipeline(
        self,
        *,
        keyword: str,
        video_limit: int = 5,
        days: int = 3,
        video_publish_days: int | None = None,
        region: str | None = None,
        headless: bool | None = None,
        agent_fallback: bool = True,
        provider: str = "deepseek",
        timeout_seconds: int = 600,
        force_refresh: bool = False,
        cache_ttl_hours: float = 24,
        guest_mode: bool = False,
        session: AgentBrowserSession | None = None,
    ) -> dict[str, Any]:
        """对外 Pipeline：经 keyword-comments builtin 抓取。"""
        if not keyword.strip():
            return {"status": "failed", "error": "缺少 keyword", "skill_id": "pipeline-keyword-video-comments"}

        skill_id = keyword_skill_for_platform(self.platform)
        if headless is None:
            show_browser = False
        else:
            show_browser = not headless
        search_days = video_publish_days if video_publish_days is not None else None
        comment_days_param = days
        params: dict[str, Any] = {
            "keyword": keyword,
            "content_limit": video_limit,
            "video_limit": video_limit,
            "limit": video_limit,
            "region": region,
            "show_browser": show_browser,
            "guest_mode": guest_mode,
            "force_refresh": force_refresh,
            "cache_ttl_hours": cache_ttl_hours,
            "provider": provider,
        }
        if search_days is not None:
            params["video_publish_days"] = search_days
        if comment_days_param is not None:
            params["comment_days"] = comment_days_param
        result = await self.execute(
            skill_id,
            params,
            headless=headless,
            agent_fallback=agent_fallback,
            provider=provider,
            timeout_seconds=timeout_seconds,
            browser_session=session,
        )
        status = str(result.get("status") or "failed")
        if status != "completed":
            return {
                "status": "failed",
                "skill_id": "pipeline-keyword-video-comments",
                "error": result.get("error") or result.get("summary") or "抓取失败",
                "run_id": result.get("run_id"),
            }
        inner = result.get("result") if isinstance(result.get("result"), dict) else result
        return {
            "status": "completed",
            "skill_id": "pipeline-keyword-video-comments",
            "summary": str(result.get("summary") or inner.get("summary") or "抓取完成"),
            "result": inner,
            "run_id": result.get("run_id"),
        }

    async def _run_recovery_agent(
        self,
        *,
        task: str,
        provider: str,
        timeout_seconds: int,
        explicit_skill_ids: list[str],
    ) -> dict[str, Any]:
        agent = AgentService(
            self.settings,
            self.tenant_id,
            self.platform,
            db_session=self.db_session,
            account_id=self.account_id,
        )
        done_payload: dict[str, Any] | None = None
        run_id: str | None = None

        async def consume() -> None:
            nonlocal done_payload, run_id
            async for event in agent.run_chat(
                task,
                provider=provider,
                explicit_skill_ids=explicit_skill_ids,
                agent_profile_id="pipeline-recovery",
                mode="agent",
                run_mode="auto",
            ):
                if event.type == "session":
                    run_id = event.data.get("run_id") or run_id
                elif event.type == "done":
                    done_payload = event.data

        try:
            await asyncio.wait_for(consume(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return {
                "status": "failed",
                "error": f"Agent 兜底超时（>{timeout_seconds}s）",
                "run_id": run_id,
            }
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "run_id": run_id}

        status = str((done_payload or {}).get("status") or "failed")
        summary = str((done_payload or {}).get("summary") or "")
        result = (done_payload or {}).get("result")
        if not isinstance(result, dict):
            result = {}
        return {
            "status": status,
            "summary": summary,
            "result": result,
            "run_id": run_id,
            "error": "" if status == "completed" else summary or "Agent 兜底未完成",
        }

    @staticmethod
    def _build_instruction_task(skill: SkillOut, params: dict[str, Any]) -> str:
        parts = [f"/{skill.id}"]
        for key, value in params.items():
            if value is not None and value != "":
                parts.append(f"{key}={value}")
        parts.append("请严格按技能指南执行，完成后 task_complete。")
        return " ".join(parts)

    async def _borrow_session(self, *, headless: bool | None) -> AgentBrowserSession:
        manager = AgentSessionManager.get_instance()
        return await manager.create(
            self.tenant_id,
            self.platform,
            self.settings,
            account_id=self.account_id,
            headless=headless,
            auto_start=False,
        )

    @staticmethod
    async def _release_session(session: AgentBrowserSession) -> None:
        await AgentSessionManager.get_instance().close(session.session_id)

    async def run_open_pipeline_platform(
        self,
        req: KeywordVideoCommentsRequest,
    ) -> PlatformPipelineResult:
        result = await self.execute_keyword_pipeline(
            keyword=req.keyword,
            video_limit=req.video_limit,
            days=req.days,
            video_publish_days=req.video_publish_days,
            region=req.region,
            headless=req.headless,
            agent_fallback=True,
            provider=req.provider,
            timeout_seconds=req.timeout_seconds,
            force_refresh=req.force_refresh,
            cache_ttl_hours=req.cache_ttl_hours,
        )
        status = str(result.get("status") or "failed")
        summary = str(result.get("summary") or "")
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        return PlatformPipelineResult(
            platform=self.platform,
            status=status,
            run_id=result.get("run_id"),
            summary=summary,
            result=payload,
            error="" if status == "completed" else result.get("error") or summary or "任务未完成",
        )
