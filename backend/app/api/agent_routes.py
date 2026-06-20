from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_account_id, get_authenticated_tenant_id, get_platform_id
from app.core.config import Settings, get_settings
from app.schemas.agent import (
    AgentAsyncJobOut,
    AgentAsyncSubmitRequest,
    AgentJobConfigUpdateRequest,
    AgentBindingStatusOut,
    AgentChatRequest,
    AgentChatSyncRequest,
    AgentChatSyncResponse,
    AgentConfigOut,
    AgentProviderInfo,
    AgentStrategyOut,
    AgentResumeRequest,
    AgentResumeRunRequest,
    AgentRunListResponse,
    AgentRunOut,
    AgentRunSummaryOut,
    AgentSessionCreateRequest,
    AgentSessionOut,
    CheckpointListResponse,
    CheckpointOut,
    RestoreCheckpointRequest,
)
from app.schemas.agent_experience import (
    AgentDreamResult,
    AgentDreamRunRequest,
    AgentExperienceListResponse,
    AgentExperienceOut,
    AgentExperienceUpdate,
)
from app.schemas.agent_profile import (
    AgentProfileCreate,
    AgentProfileListResponse,
    AgentProfileOut,
    AgentProfileUpdate,
)
from app.schemas.agent_rule import (
    AgentRuleCreate,
    AgentRuleListResponse,
    AgentRuleOut,
    AgentRuleUpdate,
)
from app.schemas.skill import (
    BUILTIN_HANDLERS,
    BuiltinHandlerOut,
    SkillCreate,
    SkillEffectDetailOut,
    SkillEffectStatsOut,
    SkillExportBundle,
    SkillImportMarkdownRequest,
    SkillImportRequest,
    SkillImportResult,
    SkillListResponse,
    SkillOut,
    SkillParseMarkdownResponse,
    SkillRecordFromStepsRequest,
    SkillUpdate,
)
from app.schemas.open_pipeline import KeywordVideoCommentsRequest, KeywordVideoCommentsResponse
from app.schemas.skill_execute import SkillExecuteRequest, SkillExecuteResponse
from app.schemas.skillhub import (
    SkillHubConfigOut,
    SkillHubConfigUpdate,
    SkillHubInstallRequest,
    SkillHubInstallResult,
    SkillHubInstalledItem,
    SkillHubInstalledListResponse,
    SkillHubPublishRequest,
    SkillHubPublishResult,
    SkillHubSearchResponse,
)
from app.services.agent_dream_service import AgentDreamService
from app.services.agent_experience_store import AgentExperienceStore
from app.services.agent_profile_store import AgentProfileStore
from app.services.agent_rule_store import AgentRuleStore
from app.services.agent_browser_session import AgentSessionManager
from app.services.agent_service import AgentService
from app.services.agent_run_store import AgentRunStore
from app.services.agent_async_job_service import AgentAsyncJob, AgentAsyncJobService
from app.services.agent_job_sync_service import AgentJobSyncService
from app.schemas.external_task import ExternalTaskCapabilitiesOut, ExternalTaskCreateRequest, ExternalTaskPreflightOut
from app.services.external_task_service import get_external_capabilities, normalize_external_create
from app.services.external_task_preflight_service import run_external_task_preflight
from app.services.agent_eval_service import AgentEvalService
from app.services.open_pipeline_service import OpenPipelineService
from app.services.skill_effect_service import SkillEffectService
from app.services.skill_runner_service import SkillRunnerService
from app.services.skill_md_parser import extract_actions_from_steps, parse_skill_md, render_skill_md
from app.services.skill_store import SkillStore
from app.services.skillhub_config_store import SkillHubConfigStore
from app.services.skillhub_installer import SkillHubInstaller


router = APIRouter(prefix="/api/agent", tags=["agent"])


def _async_job_out(
    job: AgentAsyncJob,
    settings: Settings | None = None,
    *,
    db_session: Session | None = None,
) -> AgentAsyncJobOut:
    sync = (
        AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)
        if settings is not None
        else {}
    )
    return AgentAsyncJobOut(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        retry_count=job.retry_count,
        run_id=job.run_id,
        session_id=job.session_id,
        message=job.message,
        provider=job.provider,
        mode=job.mode,
        run_mode=job.run_mode,
        platform=job.platform,
        account_id=job.account_id,
        timeout_seconds=job.timeout_seconds,
        max_retries=job.max_retries,
        priority=job.priority,
        auto_execute=job.auto_execute,
        auto_restart=job.auto_restart,
        result=job.result,
        sync=sync,
        error=job.error,
        dead_letter_reason=job.dead_letter_reason,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _agent_service(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> AgentService:
    return AgentService(settings, tenant_id, platform, db_session=session, account_id=account_id)


def _skill_store(settings: Settings = Depends(get_settings)) -> SkillStore:
    return SkillStore(settings)


def _rule_store(settings: Settings = Depends(get_settings)) -> AgentRuleStore:
    return AgentRuleStore(settings)


def _profile_store(settings: Settings = Depends(get_settings)) -> AgentProfileStore:
    return AgentProfileStore(settings)


def _experience_store(settings: Settings = Depends(get_settings)) -> AgentExperienceStore:
    return AgentExperienceStore(settings)


@router.get("/bindings/status", response_model=AgentBindingStatusOut)
def agent_binding_status(
    agent: AgentService = Depends(_agent_service),
) -> AgentBindingStatusOut:
    return AgentBindingStatusOut.model_validate(agent.platform_binding_status())


@router.get("/config", response_model=AgentConfigOut)
def get_agent_config(
    agent: AgentService = Depends(_agent_service),
) -> AgentConfigOut:
    raw = agent.get_config()
    providers = {
        name: AgentProviderInfo(**info)
        for name, info in raw["providers"].items()
    }
    return AgentConfigOut(
        default_provider=raw["default_provider"],
        default_run_mode=raw["default_run_mode"],
        dream_enabled=raw.get("dream_enabled", True),
        dream_auto=raw.get("dream_auto", True),
        providers=providers,
    )


@router.post("/sessions", response_model=AgentSessionOut)
async def create_session(
    payload: AgentSessionCreateRequest,
    agent: AgentService = Depends(_agent_service),
) -> AgentSessionOut:
    session = await agent.create_session(headless=payload.headless)
    info = await session.page_info()
    return AgentSessionOut(
        session_id=session.session_id,
        platform=session.platform,
        tenant_id=session.tenant_id,
        url=info["url"],
        title=info["title"],
    )


@router.delete("/sessions/{session_id}")
async def close_session(
    session_id: str,
    agent: AgentService = Depends(_agent_service),
) -> dict[str, bool]:
    closed = await agent.close_session(session_id)
    if not closed:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"closed": True}


@router.get("/sessions/{session_id}", response_model=AgentSessionOut)
async def get_session(
    session_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    platform: str = Depends(get_platform_id),
) -> AgentSessionOut:
    session = AgentSessionManager.get_instance().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    if session.account_id != account_id:
        raise HTTPException(status_code=403, detail="无权访问该账号的会话")
    if session.platform != platform:
        raise HTTPException(status_code=403, detail="会话平台不匹配")
    info = await session.page_info()
    return AgentSessionOut(
        session_id=session.session_id,
        platform=session.platform,
        tenant_id=session.tenant_id,
        url=info["url"],
        title=info["title"],
    )


@router.get("/sessions/{session_id}/tab-audit")
async def get_session_tab_audit(
    session_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    platform: str = Depends(get_platform_id),
) -> dict:
    """返回浏览器会话内 tab 创建/关闭审计（排查 popup 闪动）。"""
    manager = AgentSessionManager.get_instance()
    browser_session = manager.get(session_id)
    if browser_session is None:
        browser_session = manager.find_reusable_stable(tenant_id, platform, account_id)
    if browser_session is None:
        raise HTTPException(status_code=404, detail="浏览器会话不存在")
    if browser_session.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    events = browser_session.tab_audit_events()
    return {
        "session_id": browser_session.session_id,
        "platform": browser_session.platform,
        "tenant_id": browser_session.tenant_id,
        "account_id": browser_session.account_id,
        "count": len(events),
        "events": events,
    }


@router.post("/chat")
async def agent_chat(
    payload: AgentChatRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
):
    from app.platforms.account_id import normalize_account_id

    effective_account = normalize_account_id(payload.account_id or account_id)
    agent = AgentService(
        settings,
        tenant_id,
        platform,
        db_session=session,
        account_id=effective_account,
    )

    async def event_stream():
        run_id = payload.run_id
        try:
            async for event in agent.run_chat(
                payload.message,
                session_id=payload.session_id,
                run_id=run_id,
                provider=payload.provider,
                headless=payload.headless,
                explicit_skill_ids=payload.explicit_skill_ids,
                agent_profile_id=payload.agent_profile_id,
                mode=payload.mode,
                run_mode=payload.run_mode,
            ):
                if event.type == "session" and not run_id:
                    run_id = event.data.get("run_id")
                yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            if run_id:
                agent._mark_run_interrupted(run_id)
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/sync", response_model=AgentChatSyncResponse)
async def agent_chat_sync(
    payload: AgentChatSyncRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> AgentChatSyncResponse:
    from app.platforms.account_id import normalize_account_id

    effective_account = normalize_account_id(payload.account_id or account_id)
    agent = AgentService(
        settings,
        tenant_id,
        platform,
        db_session=session,
        account_id=effective_account,
    )

    run_id = payload.run_id
    session_id = payload.session_id
    done_payload: dict[str, Any] | None = None
    last_assistant_message = ""

    async def consume() -> None:
        nonlocal run_id, session_id, done_payload, last_assistant_message
        async for event in agent.run_chat(
            payload.message,
            session_id=payload.session_id,
            run_id=payload.run_id,
            provider=payload.provider,
            headless=payload.headless,
            explicit_skill_ids=payload.explicit_skill_ids,
            agent_profile_id=payload.agent_profile_id,
            mode=payload.mode,
            run_mode=payload.run_mode,
        ):
            if event.type == "session":
                run_id = event.data.get("run_id") or run_id
                session_id = event.data.get("session_id") or session_id
            elif event.type == "message":
                content = str(event.data.get("content") or "").strip()
                if content:
                    last_assistant_message = content
            elif event.type == "done":
                done_payload = event.data

    try:
        await asyncio.wait_for(consume(), timeout=payload.timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=408,
            detail=f"智能体执行超时（>{payload.timeout_seconds}s），可使用 run_id 继续查询",
        ) from exc

    if not run_id:
        raise HTTPException(status_code=500, detail="未生成 run_id")

    run = agent.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=500, detail="执行结束但未找到 Run 记录")

    phase = run.loop_state.phase if run.loop_state else ""
    task_snapshot = run.loop_state.task_snapshot if run.loop_state else {}
    summary = str((done_payload or {}).get("summary") or "")
    status = str((done_payload or {}).get("status") or run.status)
    if not summary and last_assistant_message:
        summary = last_assistant_message

    return AgentChatSyncResponse(
        run_id=run_id,
        session_id=session_id or run.browser_session_id,
        status=status,
        summary=summary,
        final_message=last_assistant_message,
        task_snapshot=task_snapshot,
        phase=phase,
        message_count=len(run.messages),
        updated_at=run.updated_at,
    )


@router.post("/pipeline/keyword-video-comments", response_model=KeywordVideoCommentsResponse)
async def pipeline_keyword_video_comments(
    payload: KeywordVideoCommentsRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> KeywordVideoCommentsResponse:
    """对外 Pipeline：按关键词搜索热门视频并抓取评论（固定 Skill 驱动）。"""
    from app.platforms.account_id import normalize_account_id

    effective_account = normalize_account_id(payload.account_id or account_id)
    svc = OpenPipelineService(settings, tenant_id, db_session=session)
    return await svc.run_keyword_video_comments(payload, account_id=effective_account)


@router.get("/strategies", response_model=list[AgentStrategyOut])
async def list_agent_strategies(
    platform: str | None = Query(default=None),
) -> list[AgentStrategyOut]:
    from app.services.agent_strategy import list_strategies

    return [AgentStrategyOut.model_validate(item) for item in list_strategies(platform=platform)]


@router.get("/external/capabilities", response_model=ExternalTaskCapabilitiesOut)
async def get_external_task_capabilities() -> ExternalTaskCapabilitiesOut:
    """外部系统集成：查询 Huoke 支持的任务意图与字段定义。"""
    return get_external_capabilities()


@router.post("/external/preflight", response_model=ExternalTaskPreflightOut)
async def preflight_external_agent_task(
    payload: ExternalTaskCreateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
) -> ExternalTaskPreflightOut:
    """创建前预检：Sidecar/登录/编排/Skill/LLM 评估是否就绪。"""
    effective_platform = str(payload.platform or platform)
    effective_payload = payload.model_copy(update={"platform": effective_platform})
    return await run_external_task_preflight(
        effective_payload,
        settings=settings,
        tenant_id=tenant_id,
        account_id=account_id,
    )


@router.post("/external/jobs", response_model=AgentAsyncJobOut)
async def create_external_agent_job(
    payload: ExternalTaskCreateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
) -> AgentAsyncJobOut:
    """外部系统集成：按 intent + scope 创建任务（参数归一化在 Huoke 内完成）。"""
    message, config, correlation = normalize_external_create(payload)
    svc = AgentAsyncJobService.get(settings)
    job = await svc.submit_async(
        tenant_id=tenant_id,
        platform=str(payload.platform or platform),
        account_id=account_id,
        message=message,
        provider=payload.provider,
        mode="agent",
        run_mode="auto",
        timeout_seconds=payload.timeout_seconds,
        max_retries=payload.max_retries,
        priority=payload.priority,
        webhook_url=payload.webhook_url,
        webhook_headers=payload.webhook_headers,
        auto_execute=payload.auto_execute,
        auto_restart=payload.auto_restart,
        agent_strategy=payload.agent_strategy,
        config=config,
        correlation=correlation,
    )
    return _async_job_out(job, settings)


@router.post("/jobs", response_model=AgentAsyncJobOut)
async def submit_agent_job(
    payload: AgentAsyncSubmitRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
) -> AgentAsyncJobOut:
    svc = AgentAsyncJobService.get(settings)
    job = await svc.submit_async(
        tenant_id=tenant_id,
        platform=platform,
        account_id=account_id,
        message=payload.message,
        provider=payload.provider,
        mode=payload.mode,
        run_mode=payload.run_mode,
        timeout_seconds=payload.timeout_seconds,
        max_retries=payload.max_retries,
        priority=payload.priority,
        webhook_url=payload.webhook_url,
        webhook_headers=payload.webhook_headers,
        auto_execute=payload.auto_execute,
        auto_restart=payload.auto_restart,
        agent_strategy=payload.agent_strategy,
        config=payload.config,
    )
    return _async_job_out(job, settings)


@router.patch("/jobs/{job_id}/config", response_model=AgentAsyncJobOut)
async def update_agent_job_config(
    job_id: str,
    payload: AgentJobConfigUpdateRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> AgentAsyncJobOut:
    """创建后通过自然语言或 JSON 修改任务配置（简报、目标、约束等）。"""
    if not (payload.message or "").strip() and not payload.config:
        raise HTTPException(status_code=400, detail="请提供 message 或 config")
    svc = AgentAsyncJobService.get(settings)
    try:
        job = await svc.update_config(
            tenant_id,
            job_id,
            message=payload.message or "",
            config=payload.config,
            provider=payload.provider,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "不存在" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from exc
    return _async_job_out(job, settings)


@router.post("/jobs/{job_id}/execute", response_model=AgentAsyncJobOut)
async def execute_agent_job(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> AgentAsyncJobOut:
    svc = AgentAsyncJobService.get(settings)
    try:
        job = svc.execute(tenant_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _async_job_out(job, settings)


@router.get("/jobs/{job_id}", response_model=AgentAsyncJobOut)
async def get_agent_job(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> AgentAsyncJobOut:
    svc = AgentAsyncJobService.get(settings)
    job = svc.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _async_job_out(job, settings, db_session=session)


@router.get("/jobs/{job_id}/diagnosis")
async def get_agent_job_diagnosis(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    from app.services.page_diagnosis.reporter import extract_page_diagnosis

    svc = AgentAsyncJobService.get(settings)
    job = svc.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    diagnosis = extract_page_diagnosis(job.result if isinstance(job.result, dict) else {})
    if not diagnosis:
        raise HTTPException(status_code=404, detail="暂无页面诊断")
    return {"job_id": job_id, "diagnosis": diagnosis}


@router.get("/jobs/{job_id}/diagnosis/screenshot")
async def get_agent_job_diagnosis_screenshot(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    from fastapi.responses import FileResponse

    from app.services.page_diagnosis.reporter import extract_page_diagnosis
    from app.services.page_diagnosis.screenshot_store import resolve_screenshot_path

    svc = AgentAsyncJobService.get(settings)
    job = svc.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    diagnosis = extract_page_diagnosis(job.result if isinstance(job.result, dict) else {})
    if not diagnosis:
        raise HTTPException(status_code=404, detail="暂无页面诊断")
    screenshot_ref = str(diagnosis.get("screenshot_ref") or "").strip()
    if not screenshot_ref:
        raise HTTPException(status_code=404, detail="暂无诊断截图")
    path = resolve_screenshot_path(settings, screenshot_ref)
    if path is None:
        raise HTTPException(status_code=404, detail="截图不存在或已过期")
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.get("/jobs", response_model=list[AgentAsyncJobOut])
async def list_agent_jobs(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AgentAsyncJobOut]:
    svc = AgentAsyncJobService.get(settings)
    items = svc.list_jobs(tenant_id, limit=limit)
    return [_async_job_out(j, settings, db_session=session) for j in items]


@router.post("/jobs/{job_id}/cancel")
async def cancel_agent_job(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    svc = AgentAsyncJobService.get(settings)
    cancelled = svc.cancel(tenant_id, job_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job_id": job_id, "cancelled": True}


@router.post("/jobs/{job_id}/pause")
async def pause_agent_job(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    svc = AgentAsyncJobService.get(settings)
    try:
        paused = svc.pause(tenant_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not paused:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job_id": job_id, "paused": True}


@router.delete("/jobs/{job_id}")
@router.post("/jobs/{job_id}/delete")
async def delete_agent_job(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """删除编排任务（含沙盒）；运行中需先取消。POST /delete 与 DELETE 等价。"""
    svc = AgentAsyncJobService.get(settings)
    try:
        deleted = svc.delete_job(tenant_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job_id": job_id, "deleted": True}


@router.delete("/jobs/{job_id}/sandbox")
async def destroy_agent_job_sandbox(
    job_id: str,
    delete_job: bool = False,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """删除任务沙盒（目录+SQLite+代码）；delete_job=true 时连同 job 元数据一并删除。"""
    svc = AgentAsyncJobService.get(settings)
    job = svc.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    ok = svc.destroy_sandbox(tenant_id, job_id, delete_job=delete_job)
    if not ok and not delete_job:
        raise HTTPException(status_code=404, detail="沙盒不存在")
    return {"job_id": job_id, "sandbox_destroyed": ok, "job_deleted": delete_job}


@router.post("/eval/benchmark")
async def run_agent_benchmark(
    payload: dict[str, Any],
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    cases = payload.get("cases") or []
    if not isinstance(cases, list) or not cases:
        raise HTTPException(status_code=400, detail="cases 不能为空")
    svc = AgentEvalService(settings, tenant_id, platform, account_id)
    return await svc.run_benchmark(cases)


@router.post("/resume/approval")
async def resume_approval(
    payload: AgentResumeRequest,
    agent: AgentService = Depends(_agent_service),
):
    async def event_stream():
        async for event in agent.resume_approval(payload.run_id, approved=payload.approved):
            yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/resume/plan")
async def resume_plan(
    payload: AgentResumeRequest,
    agent: AgentService = Depends(_agent_service),
):
    async def event_stream():
        async for event in agent.resume_plan(payload.run_id, approved=payload.approved):
            yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/resume/run")
async def resume_run(
    payload: AgentResumeRunRequest,
    agent: AgentService = Depends(_agent_service),
):
    async def event_stream():
        try:
            async for event in agent.resume_run(payload.run_id):
                yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            agent._mark_run_interrupted(payload.run_id)
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/rules", response_model=AgentRuleListResponse)
def list_rules(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentRuleStore = Depends(_rule_store),
) -> AgentRuleListResponse:
    items = store.list_all(tenant_id)
    return AgentRuleListResponse(items=items, total=len(items))


@router.post("/rules", response_model=AgentRuleOut)
def create_rule(
    payload: AgentRuleCreate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentRuleStore = Depends(_rule_store),
) -> AgentRuleOut:
    try:
        return store.create(tenant_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/rules/{rule_id}", response_model=AgentRuleOut)
def update_rule(
    rule_id: str,
    payload: AgentRuleUpdate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentRuleStore = Depends(_rule_store),
) -> AgentRuleOut:
    try:
        return store.update(tenant_id, rule_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="规则不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentRuleStore = Depends(_rule_store),
) -> dict[str, bool]:
    deleted = store.delete(tenant_id, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"deleted": True}


@router.get("/profiles", response_model=AgentProfileListResponse)
def list_agent_profiles(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    store: AgentProfileStore = Depends(_profile_store),
) -> AgentProfileListResponse:
    items = store.list_all(tenant_id, platform=platform)
    return AgentProfileListResponse(items=items, total=len(items))


@router.post("/profiles", response_model=AgentProfileOut)
def create_agent_profile(
    payload: AgentProfileCreate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentProfileStore = Depends(_profile_store),
) -> AgentProfileOut:
    try:
        return store.create(tenant_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/profiles/{profile_id}", response_model=AgentProfileOut)
def update_agent_profile(
    profile_id: str,
    payload: AgentProfileUpdate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentProfileStore = Depends(_profile_store),
) -> AgentProfileOut:
    try:
        return store.update(tenant_id, profile_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 档案不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/profiles/{profile_id}")
def delete_agent_profile(
    profile_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentProfileStore = Depends(_profile_store),
) -> dict[str, bool]:
    deleted = store.delete(tenant_id, profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent 档案不存在")
    return {"deleted": True}


@router.get("/skills", response_model=SkillListResponse)
def list_skills(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> SkillListResponse:
    items = store.list_all(tenant_id, include_disabled=True)
    return SkillListResponse(items=items, total=len(items))


@router.post("/skills/execute", response_model=SkillExecuteResponse, summary="同步执行 Skill")
async def execute_skill(
    payload: SkillExecuteRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    platform: str = Depends(get_platform_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> SkillExecuteResponse:
    from app.platforms.account_id import normalize_account_id

    effective_platform = payload.platform or platform
    effective_account = normalize_account_id(payload.account_id or account_id)
    runner = SkillRunnerService(
        settings,
        tenant_id,
        effective_platform,
        account_id=effective_account,
        db_session=session,
    )
    result = await runner.execute(
        payload.skill_id,
        payload.params,
        headless=payload.headless,
        agent_fallback=payload.agent_fallback,
        provider=payload.provider,
        timeout_seconds=payload.timeout_seconds,
    )
    status = str(result.get("status") or ("completed" if not result.get("error") else "failed"))
    ok = status == "completed" and not result.get("error")
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    return SkillExecuteResponse(
        ok=ok,
        skill_id=payload.skill_id,
        platform=effective_platform,
        tenant_id=tenant_id,
        account_id=effective_account,
        status=status,
        summary=str(result.get("summary") or ""),
        result=inner if isinstance(inner, dict) else {},
        error=str(result.get("error") or ""),
        recovery_stage=result.get("recovery_stage"),
        run_id=result.get("run_id"),
    )


@router.get("/skills/effects", response_model=list[SkillEffectStatsOut])
def list_skill_effects(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
    settings: Settings = Depends(get_settings),
) -> list[SkillEffectStatsOut]:
    items = store.list_all(tenant_id, include_disabled=True)
    svc = SkillEffectService(AgentRunStore(settings), tenant_id)
    return [svc.get_skill_detail(item.id, limit=20).stats for item in items]


@router.get("/skills/{skill_id}/effect", response_model=SkillEffectDetailOut)
def get_skill_effect(
    skill_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
    settings: Settings = Depends(get_settings),
    limit: int = Query(default=20, ge=1, le=100),
) -> SkillEffectDetailOut:
    skill = store.get(tenant_id, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    svc = SkillEffectService(AgentRunStore(settings), tenant_id)
    return svc.get_skill_detail(skill_id, limit=limit)


@router.get("/skills/builtin-handlers", response_model=list[BuiltinHandlerOut])
def list_builtin_handlers() -> list[BuiltinHandlerOut]:
    return [
        BuiltinHandlerOut(id=handler_id, description=desc)
        for handler_id, desc in BUILTIN_HANDLERS.items()
    ]


@router.post("/skills", response_model=SkillOut)
def create_skill(
    payload: SkillCreate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> SkillOut:
    try:
        return store.create(tenant_id, payload, scope="tenant")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/skills/{skill_id}", response_model=SkillOut)
def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> SkillOut:
    try:
        return store.update(tenant_id, skill_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="技能不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/skills/{skill_id}")
def delete_skill(
    skill_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> dict[str, bool]:
    try:
        deleted = store.delete(tenant_id, skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"deleted": True}


@router.get("/runs", response_model=AgentRunListResponse)
def list_agent_runs(
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    agent: AgentService = Depends(_agent_service),
) -> AgentRunListResponse:
    items = [
        AgentRunSummaryOut.model_validate(item)
        for item in agent.list_runs(limit=limit)
    ]
    return AgentRunListResponse(items=items, total=len(items))


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_agent_run(
    run_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    agent: AgentService = Depends(_agent_service),
) -> AgentRunOut:
    run = agent.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="对话 Run 不存在")
    if run.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该 Run")
    return AgentRunOut(
        run_id=run.run_id,
        browser_session_id=run.browser_session_id,
        tenant_id=run.tenant_id,
        platform=run.platform,
        provider=run.provider,
        status=run.status,
        mode=run.mode,
        run_mode=run.run_mode,
        agent_profile_id=run.agent_profile_id or "default",
        message_count=len(run.messages),
        messages=run.messages,
        pending_plan=run.pending_plan.model_dump() if run.pending_plan else None,
        pending_approval=run.pending_approval.model_dump() if run.pending_approval else None,
        review_report=run.review_report or {},
        validation_report=run.validation_report or {},
        resumable=run.loop_state is not None and run.status in {"active", "interrupted"},
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.delete("/runs/{run_id}")
def delete_agent_run(
    run_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    agent: AgentService = Depends(_agent_service),
) -> dict[str, bool]:
    run = agent.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="对话 Run 不存在")
    if run.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该 Run")
    deleted = agent.delete_run(run_id)
    return {"deleted": deleted}


@router.post("/runs/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    agent: AgentService = Depends(_agent_service),
) -> dict[str, Any]:
    run = agent.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="对话 Run 不存在")
    if run.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该 Run")
    cancelled = await agent.cancel_run(run_id)
    return {"run_id": run_id, "cancelled": cancelled}


@router.get("/runs/{run_id}/checkpoints", response_model=CheckpointListResponse)
def list_run_checkpoints(
    run_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    agent: AgentService = Depends(_agent_service),
) -> CheckpointListResponse:
    run = agent.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="对话 Run 不存在")
    if run.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该 Run")
    items = agent.list_checkpoints(run_id)
    return CheckpointListResponse(
        items=[
            CheckpointOut(
                checkpoint_id=c.checkpoint_id,
                run_id=c.run_id,
                step=c.step,
                tool=c.tool,
                url=c.url,
                title=c.title,
                created_at=c.created_at,
            )
            for c in items
        ],
        total=len(items),
    )


@router.post("/runs/{run_id}/checkpoints/restore")
async def restore_run_checkpoint(
    run_id: str,
    payload: RestoreCheckpointRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    agent: AgentService = Depends(_agent_service),
) -> dict[str, Any]:
    run = agent.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="对话 Run 不存在")
    if run.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="无权访问该 Run")
    try:
        return await agent.restore_checkpoint(run_id, payload.checkpoint_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/skills/export")
def export_skills_json(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
    ids: str | None = Query(default=None, description="逗号分隔的技能 ID，留空导出全部租户技能"),
) -> SkillExportBundle:
    skill_ids = [s.strip() for s in ids.split(",") if s.strip()] if ids else None
    skills = store.export_tenant_skills(tenant_id, skill_ids)
    return SkillExportBundle(skills=skills)


@router.get("/skills/{skill_id}/export.md")
def export_skill_markdown(
    skill_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> PlainTextResponse:
    skill = store.get(tenant_id, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    content = render_skill_md(skill.model_dump(mode="json"))
    filename = f"{skill_id}-SKILL.md"
    return PlainTextResponse(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/skills/{skill_id}/export.json")
def export_skill_json(
    skill_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> Response:
    skill = store.get(tenant_id, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    payload = {k: v for k, v in skill.model_dump(mode="json").items() if k not in {"scope", "tool_name"}}
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{skill_id}.json"'},
    )


@router.post("/skills/import/json", response_model=SkillImportResult)
def import_skills_json(
    payload: SkillImportRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> SkillImportResult:
    imported, skipped, errors = store.import_skills(
        tenant_id,
        payload.skills,
        overwrite=payload.overwrite,
    )
    return SkillImportResult(imported=imported, skipped=skipped, errors=errors)


@router.post("/skills/import/markdown", response_model=SkillOut)
def import_skill_markdown(
    payload: SkillImportMarkdownRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> SkillOut:
    try:
        skill = parse_skill_md(payload.content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing = store.get(tenant_id, skill.id)
    try:
        if existing and existing.scope == "tenant":
            if payload.overwrite:
                return store.update(tenant_id, skill.id, SkillUpdate(**skill.model_dump()))
            raise HTTPException(status_code=409, detail=f"技能已存在: {skill.id}")
        if existing and existing.scope == "global" and not payload.overwrite:
            raise HTTPException(status_code=409, detail=f"技能 ID 与全局技能冲突: {skill.id}")
        return store.create(tenant_id, skill, scope="tenant")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/parse-markdown", response_model=SkillParseMarkdownResponse)
def parse_skill_markdown(payload: SkillImportMarkdownRequest) -> SkillParseMarkdownResponse:
    try:
        skill = parse_skill_md(payload.content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preview = render_skill_md(skill.model_dump())
    return SkillParseMarkdownResponse(skill=skill, markdown_preview=preview)


@router.post("/skills/record-from-steps", response_model=SkillOut)
def record_skill_from_steps(
    payload: SkillRecordFromStepsRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: SkillStore = Depends(_skill_store),
) -> SkillOut:
    try:
        actions = extract_actions_from_steps(payload.steps)
        skill = SkillCreate(
            id=payload.id,
            name=payload.name,
            description=payload.description,
            type="actions",
            parameters=payload.parameters,
            actions=actions,
        )
        return store.create(tenant_id, skill, scope="tenant")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _skillhub_config_out(settings: Settings, tenant_id: str) -> SkillHubConfigOut:
    store = SkillHubConfigStore(settings)
    data = store.load(tenant_id)
    token = store.get_token(tenant_id)
    return SkillHubConfigOut(
        registry=store.get_registry(tenant_id),
        token_configured=bool(token),
        auto_install_enabled=store.is_auto_install_enabled(tenant_id),
    )


@router.get("/skills/hub/config", response_model=SkillHubConfigOut)
def get_skillhub_config(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> SkillHubConfigOut:
    return _skillhub_config_out(settings, tenant_id)


@router.put("/skills/hub/config", response_model=SkillHubConfigOut)
def update_skillhub_config(
    payload: SkillHubConfigUpdate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> SkillHubConfigOut:
    store = SkillHubConfigStore(settings)
    data = store.load(tenant_id)
    if payload.registry is not None:
        data["registry"] = payload.registry.rstrip("/")
    if payload.clear_token:
        data.pop("token", None)
    elif payload.token is not None:
        data["token"] = payload.token.strip() or None
    if payload.auto_install_enabled is not None:
        data["auto_install_enabled"] = payload.auto_install_enabled
    store.save(tenant_id, data)
    return _skillhub_config_out(settings, tenant_id)


@router.get("/skills/hub/search", response_model=SkillHubSearchResponse)
async def search_skillhub(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> SkillHubSearchResponse:
    installer = SkillHubInstaller(settings, tenant_id)
    try:
        data = await installer.search(q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    from app.schemas.skillhub import SkillHubSearchItem

    items = [
        SkillHubSearchItem(
            namespace=i.get("namespace", "global"),
            slug=i.get("slug", ""),
            latest_version=i.get("latestVersion") or i.get("latest_version") or "",
            summary=i.get("summary", ""),
        )
        for i in (data.get("items") or [])
    ]
    return SkillHubSearchResponse(
        items=items,
        total=int(data.get("total") or len(items)),
        limit=limit,
    )


@router.post("/skills/hub/install-zip", response_model=SkillHubInstallResult)
async def install_skillhub_zip(
    file: UploadFile = File(...),
    overwrite: bool = Query(default=False),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> SkillHubInstallResult:
    import tempfile
    from pathlib import Path

    from app.schemas.skill import SkillUpdate
    from app.services.skillhub_package import extract_zip_to_dir, parse_skill_md_from_package

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    installer = SkillHubInstaller(settings, tenant_id)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            extract_zip_to_dir(content, tmp_path)
            skill_create = parse_skill_md_from_package(tmp_path)
        target_dir = installer.package_dir(skill_create.id)
        extract_zip_to_dir(content, target_dir)
        skill_create.source = "skillhub"
        skill_create.package_path = str(target_dir)
        skill_create.hub_namespace = "local"
        skill_create.hub_version = "upload"
        existing = installer.skill_store.get(tenant_id, skill_create.id)
        if existing and existing.scope == "tenant" and not overwrite:
            raise HTTPException(status_code=409, detail=f"技能已存在: {skill_create.id}")
        if existing and existing.scope == "tenant":
            skill_out = installer.skill_store.update(
                tenant_id,
                skill_create.id,
                SkillUpdate(**{k: v for k, v in skill_create.model_dump().items() if k != "id"}),
            )
        else:
            skill_out = installer.skill_store.create(tenant_id, skill_create, scope="tenant")
        installer._upsert_install_record(
            slug=skill_create.id,
            namespace="local",
            version="upload",
            skill_id=skill_out.id,
            package_dir=str(target_dir),
            fingerprint=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillHubInstallResult(
        skill=skill_out.model_dump(mode="json"),
        namespace="local",
        slug=skill_create.id,
        version="upload",
        package_dir=str(target_dir),
        installed=True,
        message=f"已从 zip 安装技能 {skill_create.id}",
    )


@router.post("/skills/hub/install", response_model=SkillHubInstallResult)
async def install_skillhub(
    payload: SkillHubInstallRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> SkillHubInstallResult:
    installer = SkillHubInstaller(settings, tenant_id)
    try:
        result = await installer.install(
            coordinate=payload.coordinate,
            namespace=payload.namespace,
            slug=payload.slug,
            version=payload.version,
            overwrite=payload.overwrite or payload.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SkillHubInstallResult(**result)


@router.get("/skills/hub/installed", response_model=SkillHubInstalledListResponse)
def list_skillhub_installed(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> SkillHubInstalledListResponse:
    installer = SkillHubInstaller(settings, tenant_id)
    items = [
        SkillHubInstalledItem(
            slug=i["slug"],
            namespace=i.get("namespace", "global"),
            version=i.get("version", ""),
            skill_id=i.get("skill_id", i["slug"]),
            package_dir=i.get("package_dir", ""),
            registry=i.get("registry", ""),
            installed_at=i.get("installed_at"),
            fingerprint=i.get("fingerprint"),
        )
        for i in installer.list_installed()
    ]
    return SkillHubInstalledListResponse(items=items)


@router.delete("/skills/hub/installed/{slug}")
def uninstall_skillhub(
    slug: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    installer = SkillHubInstaller(settings, tenant_id)
    removed = installer.uninstall(slug)
    return {"deleted": removed}


@router.post("/skills/hub/publish", response_model=SkillHubPublishResult)
async def publish_skillhub(
    payload: SkillHubPublishRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> SkillHubPublishResult:
    installer = SkillHubInstaller(settings, tenant_id)
    try:
        result = await installer.publish_local_skill(
            payload.skill_id,
            namespace=payload.namespace,
            visibility=payload.visibility,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SkillHubPublishResult(
        namespace=result.get("namespace", payload.namespace),
        slug=result.get("slug", payload.skill_id),
        version=str(result.get("version", "")),
        visibility=str(result.get("visibility", payload.visibility)),
    )


@router.get("/experiences", response_model=AgentExperienceListResponse)
def list_experiences(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentExperienceStore = Depends(_experience_store),
) -> AgentExperienceListResponse:
    items = store.list_all(tenant_id, include_disabled=True)
    return AgentExperienceListResponse(items=items, total=len(items))


@router.put("/experiences/{experience_id}", response_model=AgentExperienceOut)
def update_experience(
    experience_id: str,
    payload: AgentExperienceUpdate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentExperienceStore = Depends(_experience_store),
) -> AgentExperienceOut:
    try:
        return store.update(tenant_id, experience_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="经验不存在") from exc


@router.delete("/experiences/{experience_id}")
def delete_experience(
    experience_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    store: AgentExperienceStore = Depends(_experience_store),
) -> dict[str, bool]:
    deleted = store.delete(tenant_id, experience_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="经验不存在")
    return {"deleted": True}


@router.post("/dream/consolidate", response_model=AgentDreamResult)
async def consolidate_dreams(
    limit: int = Query(default=30, ge=1, le=100),
    payload: AgentDreamRunRequest | None = None,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
    agent: AgentService = Depends(_agent_service),
) -> AgentDreamResult:
    use_llm = payload.use_llm if payload else False
    client, model = agent._resolve_client(agent.get_config()["default_provider"])
    dream = AgentDreamService(settings, tenant_id)
    return await dream.consolidate_recent(
        limit=limit,
        use_llm=use_llm,
        client=client,
        model=model,
    )


@router.post("/dream/runs/{run_id}", response_model=AgentExperienceOut)
async def dream_from_run(
    run_id: str,
    payload: AgentDreamRunRequest | None = None,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
    agent: AgentService = Depends(_agent_service),
) -> AgentExperienceOut:
    use_llm = payload.use_llm if payload else False
    client, model = agent._resolve_client(agent.get_config()["default_provider"])
    dream = AgentDreamService(settings, tenant_id)
    created = await dream.dream_from_run(
        run_id,
        use_llm=use_llm,
        client=client,
        model=model,
    )
    if created is None:
        raise HTTPException(status_code=400, detail="无法从该对话提炼经验（可能已处理过或对话过短）")
    item = dream.experience_store.get(tenant_id, created.id)
    if item is None:
        raise HTTPException(status_code=500, detail="经验创建失败")
    return item
