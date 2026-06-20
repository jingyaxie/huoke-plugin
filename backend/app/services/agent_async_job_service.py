from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.agent_browser_session import AgentSessionManager
from app.services.agent_job_plan_service import build_orchestration_plan, sync_orchestration_status
from app.services.task_sandbox_runtime import TaskSandboxRuntime
from app.services.task_brief_service import TaskBrief
from app.services.task_config_update_service import brief_to_job_message, update_task_config
from app.services.task_sandbox_service import TaskSandboxService
from app.services.task_supervisor_service import TaskSupervisorService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentAsyncJob(BaseModel):
    job_id: str
    tenant_id: str
    platform: str
    account_id: str
    message: str
    provider: str = "deepseek"
    mode: str = "agent"
    run_mode: str = "auto"
    auto_execute: bool = True
    auto_restart: bool = True
    timeout_seconds: int = 600
    max_retries: int = 1
    priority: int = 5
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = Field(default_factory=dict)
    correlation: dict[str, Any] = Field(default_factory=dict)
    status: str = "queued"
    stage: str = "plan"
    retry_count: int = 0
    run_id: str | None = None
    session_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    dead_letter_reason: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class _JobKey:
    tenant_id: str
    job_id: str


class AgentAsyncJobService:
    _instance: "AgentAsyncJobService | None" = None
    RESTARTABLE_STATUSES = frozenset({"pending", "cancelled", "failed", "dead_letter", "completed"})

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root / "tenants"
        self.root.mkdir(parents=True, exist_ok=True)
        self._running_jobs: dict[str, asyncio.Task[None]] = {}
        self._pause_jobs: set[str] = set()
        self._account_active: dict[str, str] = {}
        self._queue: asyncio.PriorityQueue[tuple[int, float, str, str]] = asyncio.PriorityQueue()
        self._workers_started = False
        self._workers: list[asyncio.Task[None]] = []
        self._resume_scanner_task: asyncio.Task[None] | None = None
        self._boot_recovered = False
        self._concurrency = max(1, int(getattr(settings, "agent_job_concurrency", 2)))

    @classmethod
    def get(cls, settings: Settings) -> "AgentAsyncJobService":
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

    def _ensure_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        self._recover_active_jobs_on_startup()
        for idx in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker_loop(idx)))
        self._resume_scanner_task = asyncio.create_task(self._resume_scanner_loop())

    def _path(self, tenant_id: str, job_id: str) -> Path:
        p = self.root / tenant_id / "agent_jobs"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"{job_id}.json"

    def save(self, job: AgentAsyncJob) -> None:
        job.updated_at = _utc_now()
        if job.created_at is None:
            job.created_at = job.updated_at
        path = self._path(job.tenant_id, job.job_id)
        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def get_job(self, tenant_id: str, job_id: str) -> AgentAsyncJob | None:
        path = self._path(tenant_id, job_id)
        if not path.exists():
            return None
        job = AgentAsyncJob.model_validate(json.loads(path.read_text(encoding="utf-8")))
        self._ensure_orchestration(job)
        return job

    def _ensure_orchestration(self, job: AgentAsyncJob) -> None:
        result = job.result if isinstance(job.result, dict) else {}
        orch = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else None
        if not isinstance(orch, dict):
            return
        if job.status in {"pending", "queued"}:
            result = job.result if isinstance(job.result, dict) else {}
            state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
            has_cycles = bool(result.get("supervisor_cycles"))
            if job.status == "queued" or (not state.get("suspended") and not has_cycles):
                return

        synced = sync_orchestration_status(
            dict(orch),
            job_stage=job.stage,
            job_status=job.status,
            job_result=result,
        )
        if synced != orch:
            job.result = {
                **result,
                "execution_mode": "supervisor",
                "orchestration": synced,
                "pipeline": synced.get("steps", []),
            }
            self.save(job)

    def list_jobs(self, tenant_id: str, limit: int = 50) -> list[AgentAsyncJob]:
        d = self.root / tenant_id / "agent_jobs"
        if not d.exists():
            return []
        items: list[AgentAsyncJob] = []
        for p in d.glob("*.json"):
            try:
                items.append(AgentAsyncJob.model_validate(json.loads(p.read_text(encoding="utf-8"))))
            except Exception:
                continue
        items.sort(key=lambda x: x.updated_at or x.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return items[: max(1, limit)]

    async def _post_webhook(self, job: AgentAsyncJob) -> None:
        if not job.webhook_url:
            return
        from app.services.agent_job_sync_service import AgentJobSyncService

        payload = AgentJobSyncService(self.settings).build_payload(
            job,
            event="job.finished" if job.status in {"completed", "failed", "dead_letter", "cancelled"} else "job.updated",
        )
        headers = {
            **(job.webhook_headers or {}),
            **AgentJobSyncService(self.settings).headers_for(payload),
        }
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                await client.post(job.webhook_url, json=payload, headers=headers)
            except Exception as exc:
                self._append_progress(job, "webhook_error", {"message": str(exc)})
                self.save(job)

    def _all_jobs(self) -> list[AgentAsyncJob]:
        items: list[AgentAsyncJob] = []
        for tenant_dir in self.root.glob("*"):
            d = tenant_dir / "agent_jobs"
            if not d.exists():
                continue
            for p in d.glob("*.json"):
                try:
                    items.append(AgentAsyncJob.model_validate(json.loads(p.read_text(encoding="utf-8"))))
                except Exception:
                    continue
        return items

    @staticmethod
    def _resume_due(job: AgentAsyncJob) -> bool:
        result = job.result if isinstance(job.result, dict) else {}
        state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
        if job.status != "pending" or not state.get("suspended"):
            return False
        if state.get("manual_pause"):
            return False
        return AgentAsyncJobService._resume_not_due(job) is None

    def _enqueue_job(self, job: AgentAsyncJob) -> None:
        self._queue.put_nowait((job.priority, time.time(), job.tenant_id, job.job_id))

    @staticmethod
    def _standalone_boot_resume_eligible(job: AgentAsyncJob) -> bool:
        """后端重启后：Standalone 未达目标的任务立即重新入队，不必等到次日 resume_at。"""
        result = job.result if isinstance(job.result, dict) else {}
        state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
        if job.status != "pending" or not state.get("suspended") or state.get("manual_pause"):
            return False
        plan = state.get("execution_plan") if isinstance(state.get("execution_plan"), dict) else {}
        if plan.get("pipeline") != "standalone_browse":
            return False
        if str(state.get("completion_outcome") or "") == "plan_incomplete":
            return True
        return (
            int(state.get("standalone_browse_offset") or 0) > 0
            or bool(str(state.get("standalone_search_url") or "").strip())
        )

    def _recover_active_jobs_on_startup(self) -> None:
        if self._boot_recovered:
            return
        self._boot_recovered = True
        for job in self._all_jobs():
            if job.status in {"queued", "running", "retrying"}:
                previous = job.status
                job.status = "queued"
                job.stage = "observe"
                self._append_progress(job, "status", {
                    "message": f"服务启动恢复任务（原状态 {previous}）",
                    "previous_status": previous,
                })
                self.save(job)
                self._enqueue_job(job)
            elif self._standalone_boot_resume_eligible(job):
                self._clear_suspend_for_manual_start(job)
                job.status = "queued"
                self._append_progress(job, "status", {
                    "message": "服务启动：Standalone 任务自动续扫入队",
                    "boot_auto_resume": True,
                })
                self.save(job)
                self._enqueue_job(job)
            elif self._resume_due(job):
                self._clear_suspend_for_manual_start(job)
                job.status = "queued"
                self._append_progress(job, "status", {"message": "已到自动恢复时间，任务重新入队"})
                self.save(job)
                self._enqueue_job(job)

    def enqueue_due_pending_jobs(self) -> int:
        count = 0
        for job in self._all_jobs():
            if not self._resume_due(job):
                continue
            self._clear_suspend_for_manual_start(job)
            job.status = "queued"
            self._append_progress(job, "status", {"message": "已到自动恢复时间，任务重新入队"})
            self.save(job)
            self._enqueue_job(job)
            count += 1
        return count

    async def _resume_scanner_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            self.enqueue_due_pending_jobs()

    @staticmethod
    def _append_progress(job: AgentAsyncJob, event_type: str, data: dict[str, Any]) -> None:
        result = job.result if isinstance(job.result, dict) else {}
        events = result.get("progress_events")
        if not isinstance(events, list):
            events = []
        label = AgentAsyncJobService._progress_label(event_type, data)
        events.append(
            {
                "at": _utc_now().isoformat(),
                "type": event_type,
                "label": label,
                "data": data,
            }
        )
        result["progress_events"] = events[-120:]
        job.result = result

    @staticmethod
    def _progress_label(event_type: str, data: dict[str, Any]) -> str:
        if event_type == "supervisor_decide":
            return f"Supervisor 决策 · 第 {data.get('cycle', '?')} 轮 · {data.get('action', '')}"
        if event_type == "supervisor_act_start":
            return f"Skill 执行中 · 第 {data.get('cycle', '?')} 轮 · {data.get('action', '')}"
        if event_type == "supervisor_act":
            ok = data.get("ok", True)
            return f"Skill 执行 · {data.get('action', '')} ({'成功' if ok else '失败'})"
        if event_type == "crawl_progress":
            phase = str(data.get("phase") or "").strip()
            sub = str(data.get("sub") or "").strip()
            if phase and sub:
                return f"{phase} · {sub}"
            return phase or sub or "浏览进行中"
        if event_type == "status":
            return str(data.get("message") or data.get("status") or "状态更新")
        if event_type == "done":
            return f"执行结束 · {data.get('status') or 'done'}"
        if event_type == "error":
            return f"错误 · {data.get('message') or 'unknown'}"
        if event_type == "webhook_error":
            return f"Webhook 失败 · {data.get('message') or 'unknown'}"
        if event_type == "restart":
            return str(data.get("label") or "任务重新启动")
        return event_type

    @staticmethod
    def _apply_orchestration(job: AgentAsyncJob, settings: Settings) -> None:
        result = job.result if isinstance(job.result, dict) else {}
        orch = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else None
        if not isinstance(orch, dict):
            return

        orch = dict(orch)
        orch["execution_mode"] = "supervisor"
        orch["is_preview"] = job.status in {"pending", "queued"}
        orch = sync_orchestration_status(
            orch,
            job_stage=job.stage,
            job_status=job.status,
            job_result=result,
        )

        job.result = {
            **result,
            "execution_mode": "supervisor",
            "orchestration": orch,
            "pipeline": orch.get("steps", []),
        }

    def _load_brief(self, job: AgentAsyncJob) -> TaskBrief:
        result = job.result if isinstance(job.result, dict) else {}
        orch = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {}
        raw = orch.get("task_brief") if isinstance(orch.get("task_brief"), dict) else {}
        if raw:
            return TaskBrief.model_validate(raw)
        return TaskBrief(brief_md=job.message, platform=job.platform)

    @staticmethod
    def _resume_not_due(job: AgentAsyncJob) -> str | None:
        result = job.result if isinstance(job.result, dict) else {}
        state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
        if not state.get("suspended"):
            return None
        resume_at = str(state.get("resume_at") or "").strip()
        if not resume_at:
            return None
        try:
            dt = datetime.fromisoformat(resume_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < dt:
                return resume_at
        except ValueError:
            return None
        return None

    @staticmethod
    def _account_key(tenant_id: str, platform: str, account_id: str) -> str:
        return f"{tenant_id}:{platform}:{account_id or 'default'}"

    def _defer_job_for_account_busy(self, job: AgentAsyncJob) -> bool:
        """同账号已有任务在执行时，将本任务重新入队。"""
        key = self._account_key(job.tenant_id, job.platform, job.account_id)
        active_job = self._account_active.get(key)
        if not active_job or active_job == job.job_id:
            return False
        job.status = "queued"
        job.stage = "observe"
        self._append_progress(job, "status", {
            "message": f"同账号任务 {active_job[:8]} 执行中，本任务排队等待",
        })
        self.save(job)
        self._enqueue_job(job)
        return True

    async def _run_job(self, job_key: _JobKey, settings: Settings) -> None:
        from app.db.session import SessionLocal

        job = self.get_job(job_key.tenant_id, job_key.job_id)
        if job is None:
            return

        account_key = self._account_key(job.tenant_id, job.platform, job.account_id)
        if self._defer_job_for_account_busy(job):
            return
        self._account_active[account_key] = job.job_id

        try:
            while True:
                try:
                    job = self.get_job(job_key.tenant_id, job_key.job_id)
                    if job is None:
                        return

                    result = job.result if isinstance(job.result, dict) else {}
                    state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
                    if job.status == "pending" and state.get("suspended") and state.get("manual_pause"):
                        job.stage = "act"
                        self._apply_orchestration(job, settings)
                        self.save(job)
                        return

                    resume_at = self._resume_not_due(job)
                    if resume_at:
                        job.status = "pending"
                        job.stage = "observe"
                        self._append_progress(job, "status", {
                            "message": f"未到唤醒时间，等待 resume_at={resume_at}",
                        })
                        self._apply_orchestration(job, settings)
                        self.save(job)
                        return

                    job.status = "running"
                    job.stage = "observe"
                    job.result = {
                        **(job.result if isinstance(job.result, dict) else {}),
                        "execution_mode": "supervisor",
                    }
                    self._apply_orchestration(job, settings)
                    self.save(job)

                    brief = self._load_brief(job)
                    db = SessionLocal()
                    try:
                        from app.services.dedicated_agent.service import DedicatedAgentService

                        dedicated_profile = DedicatedAgentService(settings).profile_id_from_job_result(
                            job.result if isinstance(job.result, dict) else {},
                            platform=job.platform,
                        )
                        supervisor = TaskSupervisorService(
                            settings,
                            job.tenant_id,
                            job.platform,
                            job.account_id,
                            db_session=db,
                            provider=job.provider,
                            agent_profile_id=dedicated_profile,
                        )

                        def on_progress(event_type: str, data: dict[str, Any]) -> None:
                            stage_map = {
                                "supervisor_decide": "plan",
                                "supervisor_act_start": "act",
                                "supervisor_act": "act",
                                "crawl_progress": "act",
                            }
                            job.stage = stage_map.get(event_type, job.stage)
                            self._append_progress(job, event_type, data)
                            if event_type == "crawl_progress":
                                result = job.result if isinstance(job.result, dict) else {}
                                ss = result.get("supervisor_state")
                                if not isinstance(ss, dict):
                                    ss = {}
                                live: dict[str, Any] = {}
                                for key in (
                                    "videos_processed",
                                    "leads_qualified",
                                    "comments_scanned",
                                    "target_leads",
                                    "start_video_index",
                                    "video_index",
                                ):
                                    if key in data:
                                        live[key] = data[key]
                                if live:
                                    ss["crawl_live"] = {
                                        **(ss.get("crawl_live") if isinstance(ss.get("crawl_live"), dict) else {}),
                                        **live,
                                        "phase": data.get("phase") or "",
                                        "sub": data.get("sub") or "",
                                        "at": _utc_now().isoformat(),
                                    }
                                    if "leads_qualified" in data:
                                        from app.services.task_round_service import (
                                            historical_qualified_peak_from_progress,
                                        )

                                        session_q = int(data.get("leads_qualified") or 0)
                                        if session_q > 0:
                                            ss["leads_qualified"] = max(
                                                int(ss.get("leads_qualified") or 0),
                                                session_q,
                                            )
                                    result["supervisor_state"] = ss
                                    job.result = result
                            self._apply_orchestration(job, settings)
                            self.save(job)

                        run_result = await supervisor.run(
                            brief=brief,
                            job_result=job.result if isinstance(job.result, dict) else {},
                            job_id=job.job_id,
                            timeout_seconds=job.timeout_seconds,
                            dry_run=job.run_mode == "dry_run",
                            on_progress=on_progress,
                        )
                    finally:
                        db.close()

                    status = str(run_result.get("status") or "failed")
                    summary = str(run_result.get("summary") or "")
                    browser_session_id = str(run_result.get("browser_session_id") or "").strip()
                    if browser_session_id:
                        job.session_id = browser_session_id
                    job.result = {
                        **(job.result if isinstance(job.result, dict) else {}),
                        **{k: v for k, v in run_result.items() if k not in {"status", "summary", "error"}},
                        "status": status,
                        "summary": summary,
                    }

                    if status == "completed":
                        job.stage = "dream"
                        self._apply_orchestration(job, settings)
                        job.status = "completed"
                        job.error = ""
                        self._append_progress(job, "done", {"status": "completed", "summary": summary})
                        self.save(job)
                        await self._post_webhook(job)
                        return

                    if status == "suspended":
                        job.status = "pending"
                        job.stage = "act"
                        job.error = ""
                        ss = run_result.get("supervisor_state") if isinstance(run_result.get("supervisor_state"), dict) else {}
                        progress_msg = summary or "任务已挂起，等待策略唤醒"
                        if ss.get("wake_reason"):
                            progress_msg = f"已暂停：{ss.get('wake_reason')}"
                        if ss.get("resume_at"):
                            progress_msg = f"{progress_msg}；自动恢复 {ss.get('resume_at')[:16]}"
                        if ss.get("next_action"):
                            progress_msg = f"{progress_msg}；下一步 {ss.get('next_action')}"
                        self._append_progress(job, "status", {
                            "message": progress_msg,
                            "resume_at": ss.get("resume_at"),
                            "wake_reason": ss.get("wake_reason"),
                            "next_action": ss.get("next_action"),
                        })
                        self._apply_orchestration(job, settings)
                        self.save(job)
                        await self._post_webhook(job)
                        return

                    job.stage = "act"
                    self._apply_orchestration(job, settings)

                    job.error = str(run_result.get("error") or summary or status)
                    if job.auto_restart and job.retry_count < job.max_retries:
                        job.retry_count += 1
                        job.status = "retrying"
                        self.save(job)
                        await asyncio.sleep(2)
                        continue

                    job.status = "failed" if not job.auto_restart else "dead_letter"
                    if job.status == "dead_letter":
                        job.dead_letter_reason = job.error
                    self.save(job)
                    await self._post_webhook(job)
                    return

                except asyncio.CancelledError:
                    if job.job_id in self._pause_jobs:
                        self._pause_jobs.discard(job.job_id)
                        job = self.get_job(job_key.tenant_id, job_key.job_id)
                        if job is not None:
                            self._apply_manual_pause(job)
                            self._append_progress(job, "status", {
                                "message": "用户手动暂停任务",
                                "wake_reason": self._manual_pause_reason(job),
                                "next_action": self._manual_pause_next_action(),
                            })
                            self.save(job)
                            await self._post_webhook(job)
                        return
                    job.status = "cancelled"
                    self._apply_orchestration(job, settings)
                    self.save(job)
                    return
                except Exception as exc:
                    job.retry_count += 1
                    job.error = str(exc)
                    if job.auto_restart and job.retry_count <= job.max_retries:
                        job.status = "retrying"
                        self.save(job)
                        await asyncio.sleep(2)
                        continue
                    job.status = "failed" if not job.auto_restart else "dead_letter"
                    if job.status == "dead_letter":
                        job.dead_letter_reason = str(exc)
                    self.save(job)
                    await self._post_webhook(job)
                    return
        finally:
            if self._account_active.get(account_key) == job.job_id:
                self._account_active.pop(account_key, None)

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            priority, _, tenant_id, job_id = await self._queue.get()
            _ = priority, worker_id
            key = _JobKey(tenant_id=tenant_id, job_id=job_id)
            task = asyncio.create_task(self._run_job(key, self.settings))
            self._running_jobs[job_id] = task
            try:
                await task
            finally:
                self._running_jobs.pop(job_id, None)
                self._queue.task_done()

    async def submit_async(
        self,
        *,
        tenant_id: str,
        platform: str,
        account_id: str,
        message: str,
        provider: str = "deepseek",
        mode: str = "agent",
        run_mode: str = "auto",
        auto_execute: bool = True,
        auto_restart: bool = True,
        timeout_seconds: int = 600,
        max_retries: int = 1,
        priority: int = 5,
        webhook_url: str | None = None,
        webhook_headers: dict[str, str] | None = None,
        agent_strategy: str | None = None,
        config: dict[str, Any] | None = None,
        correlation: dict[str, Any] | None = None,
    ) -> AgentAsyncJob:
        self._ensure_workers()
        orch = await build_orchestration_plan(
            message,
            settings=self.settings,
            tenant_id=tenant_id,
            provider=provider,
            agent_strategy=agent_strategy,
        )
        job_id = str(uuid.uuid4())
        brief_raw = orch.get("task_brief") if isinstance(orch.get("task_brief"), dict) else {}
        brief = TaskBrief.model_validate(brief_raw) if brief_raw else TaskBrief(brief_md=message, platform=platform)
        resolved_correlation: dict[str, Any] = dict(correlation or {})
        if isinstance(config, dict) and config:
            raw_corr = config.get("correlation")
            if isinstance(raw_corr, dict):
                resolved_correlation = {**resolved_correlation, **raw_corr}
            brief, _meta = await update_task_config(
                brief,
                config=config,
                settings=self.settings,
                tenant_id=tenant_id,
                provider=provider,
            )
            from app.services.external_task_service import enrich_brief_from_external_config

            brief = enrich_brief_from_external_config(brief, config)
            from app.services.lead_evaluation_service import (
                ensure_lead_evaluation_on_brief,
                evaluation_draft_from_payload,
            )

            eval_draft = evaluation_draft_from_payload(config.get("evaluation"))
            constraints_draft = brief.constraints.get("evaluation_draft")
            if isinstance(constraints_draft, dict):
                eval_draft = {**constraints_draft, **eval_draft}
            brief = await ensure_lead_evaluation_on_brief(
                brief,
                settings=self.settings,
                draft=eval_draft or None,
                provider=provider,
            )
            from app.services.agent_job_plan_service import _plan_from_brief

            orch = _plan_from_brief(brief)
            message = brief_to_job_message(brief)

        sandbox_svc = TaskSandboxService(self.settings, tenant_id)
        sandbox_manifest = await sandbox_svc.provision(
            job_id=job_id,
            brief=brief,
            message=message,
            provider=provider,
        )

        job = AgentAsyncJob(
            job_id=job_id,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            message=message,
            provider=provider,
            mode=mode,
            run_mode=run_mode,
            auto_execute=bool(auto_execute),
            auto_restart=bool(auto_restart),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            priority=max(1, min(10, int(priority))),
            webhook_url=webhook_url,
            webhook_headers=webhook_headers or {},
            correlation=resolved_correlation,
            status="queued" if auto_execute else "pending",
            stage="understand",
            created_at=_utc_now(),
            updated_at=_utc_now(),
            result={
                "orchestration": orch,
                "pipeline": orch.get("steps", []),
                "execution_mode": "supervisor",
                "sandbox": sandbox_manifest,
            },
        )
        self.save(job)
        if auto_execute:
            self._enqueue_job(job)
        return job

    def _clear_suspend_for_manual_start(self, job: AgentAsyncJob) -> bool:
        """用户手动启动 pending 挂起任务时，清除 resume_at 门禁以便立即执行。"""
        from app.services.task_execution_plan import (
            ensure_supervisor_execution_plan,
            reset_supervisor_state_for_manual_retry,
        )
        from app.services.task_sandbox_runtime import TaskSandboxRuntime

        result = job.result if isinstance(job.result, dict) else {}
        state = result.get("supervisor_state")
        if not isinstance(state, dict) or not state.get("suspended"):
            return False
        wake_reason = str(state.pop("wake_reason", "") or "")
        plan = state.get("execution_plan") if isinstance(state.get("execution_plan"), dict) else None
        if plan is None and isinstance(result.get("execution_plan"), dict):
            plan = result["execution_plan"]
            state["execution_plan"] = plan

        brief = self._load_brief(job)
        if brief is not None:
            state["execution_plan"] = ensure_supervisor_execution_plan(brief, state)
            plan = state.get("execution_plan")

        reset_supervisor_state_for_manual_retry(state, plan, brief=brief)
        state.pop("manual_pause", None)
        state["manual_resume_at"] = _utc_now().isoformat()
        if wake_reason:
            state["last_wake_reason"] = wake_reason

        sandbox_runtime = TaskSandboxRuntime(self.settings, job.tenant_id, job.job_id)
        if int(state.get("crawl_failures") or 0) == 0 and not state.get("crawl_done"):
            sandbox_runtime.reset_crawl_progress()

        events = result.get("progress_events")
        if not isinstance(events, list):
            events = []
        events.append({
            "at": _utc_now().isoformat(),
            "type": "manual_resume",
            "label": "手动继续执行",
            "data": {"previous_wake_reason": wake_reason or None},
        })
        result["supervisor_state"] = state
        result["progress_events"] = events[-200:]
        job.result = result
        return True

    def _prepare_job_restart(self, job: AgentAsyncJob) -> None:
        """将已取消/失败/完成的任务重置为可再次执行。"""
        job.stage = "observe"
        job.error = ""
        job.dead_letter_reason = ""
        job.retry_count = 0

        result = job.result if isinstance(job.result, dict) else {}
        orch = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {}
        steps = orch.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if step.get("id") == "understand":
                    step["status"] = "completed"
                else:
                    step["status"] = "pending"
            orch["steps"] = steps
            orch["is_preview"] = False
            orch["execution_note"] = "任务已重新启动，Supervisor 将循环执行直至目标达成或挂起。"

        events = result.get("progress_events")
        if not isinstance(events, list):
            events = []
        events.append({
            "at": _utc_now().isoformat(),
            "type": "restart",
            "label": "任务重新启动",
            "data": {"from_status": job.status},
        })

        sandbox_runtime = TaskSandboxRuntime(self.settings, job.tenant_id, job.job_id)
        sandbox_runtime.reset_restart_progress(clear_outreach=True)

        brief = self._load_brief(job)
        from app.services.task_brief_service import is_skill_flow_brief

        if is_skill_flow_brief(brief) and bool(brief.goals.get("force_refresh", True)):
            keyword = str(brief.keyword or "").strip()
            if keyword:
                try:
                    from sqlalchemy import text

                    from app.db.session import SessionLocal

                    db = SessionLocal()
                    try:
                        db.execute(
                            text(
                                "DELETE FROM crawl_cache_entries "
                                "WHERE operation = 'keyword_comments' "
                                "AND tenant_id = :tenant_id AND platform = :platform "
                                "AND params_json LIKE :kw"
                            ),
                            {
                                "tenant_id": job.tenant_id,
                                "platform": job.platform or "douyin",
                                "kw": f"%{keyword}%",
                            },
                        )
                        db.commit()
                    finally:
                        db.close()
                except Exception:
                    pass
            goals = brief.goals if isinstance(brief.goals, dict) else {}
            goals["force_refresh"] = True
            brief.goals = goals
            raw_brief = orch.get("task_brief") if isinstance(orch.get("task_brief"), dict) else {}
            raw_brief["goals"] = goals
            orch["task_brief"] = raw_brief

        job.result = {
            **result,
            "orchestration": orch,
            "pipeline": orch.get("steps", steps if isinstance(steps, list) else []),
            "execution_mode": "supervisor",
            "supervisor_state": {},
            "supervisor_cycles": [],
            "progress_events": events[-200:],
        }
        self._apply_orchestration(job, self.settings)

    def execute(self, tenant_id: str, job_id: str) -> AgentAsyncJob | None:
        """将任务入队执行；pending 首次启动，cancelled/failed/completed 可重新启动。"""
        job = self.get_job(tenant_id, job_id)
        if job is None:
            return None
        if job.status in {"running", "queued", "retrying"}:
            raise ValueError(f"任务当前为 {job.status}，请等待结束或先取消")
        if job.status not in self.RESTARTABLE_STATUSES:
            raise ValueError(f"任务状态 {job.status} 不可启动")
        if job.status == "pending":
            self._clear_suspend_for_manual_start(job)
        else:
            self._prepare_job_restart(job)
        self._ensure_workers()
        job.status = "queued"
        job.auto_execute = True
        self.save(job)
        self._enqueue_job(job)
        return job

    @staticmethod
    def _manual_pause_reason(job: AgentAsyncJob | None = None) -> str:
        if job is not None:
            result = job.result if isinstance(job.result, dict) else {}
            state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
            reason = str(state.get("wake_reason") or "").strip()
            if reason:
                return reason
        return "用户手动暂停任务"

    @staticmethod
    def _manual_pause_next_action() -> str:
        return "点击「继续执行」从当前进度恢复运行"

    def _apply_manual_pause(self, job: AgentAsyncJob, reason: str = "") -> None:
        from app.services.task_execution_plan import apply_suspend_state

        result = job.result if isinstance(job.result, dict) else {}
        state = result.get("supervisor_state")
        if not isinstance(state, dict):
            state = {}

        brief = self._load_brief(job)
        pause_reason = (reason or self._manual_pause_reason()).strip() or "用户手动暂停任务"
        apply_suspend_state(state, brief, pause_reason, resume_at="")
        state["manual_pause"] = True
        state.pop("resume_at", None)
        state["next_action"] = self._manual_pause_next_action()

        result["supervisor_state"] = state
        result["summary"] = pause_reason
        job.result = result
        job.status = "pending"
        job.stage = "act"
        job.error = ""
        self._apply_orchestration(job, self.settings)

    def pause(self, tenant_id: str, job_id: str, *, reason: str = "") -> bool:
        job = self.get_job(tenant_id, job_id)
        if job is None:
            return False
        if job.status not in {"running", "queued", "retrying"}:
            raise ValueError(f"任务当前为 {job.status}，仅运行中或排队中的任务可暂停")

        running = self._running_jobs.get(job_id)
        if running is not None and not running.done():
            self._pause_jobs.add(job_id)
            running.cancel()
            return True

        self._apply_manual_pause(job, reason)
        self._append_progress(job, "status", {
            "message": "用户手动暂停任务",
            "wake_reason": self._manual_pause_reason(job),
            "next_action": self._manual_pause_next_action(),
        })
        self.save(job)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._post_webhook(job))
        except RuntimeError:
            pass
        return True

    def cancel(self, tenant_id: str, job_id: str) -> bool:
        job = self.get_job(tenant_id, job_id)
        if job is None:
            return False
        self._pause_jobs.discard(job_id)
        t = self._running_jobs.get(job_id)
        if t and not t.done():
            t.cancel()
        if job.session_id:
            asyncio.create_task(AgentSessionManager.get_instance().close(job.session_id))
        job.status = "cancelled"
        self.save(job)
        return True

    def delete_job(self, tenant_id: str, job_id: str) -> bool:
        """删除任务元数据与沙盒；运行中/排队中需先取消。"""
        job = self.get_job(tenant_id, job_id)
        if job is None:
            return False
        if job.status in {"running", "queued", "retrying"}:
            raise ValueError("运行中或排队中的任务不可删除，请先取消")
        t = self._running_jobs.get(job_id)
        if t is not None and not t.done():
            raise ValueError("运行中或排队中的任务不可删除，请先取消")
        self.destroy_sandbox(tenant_id, job_id, delete_job=True)
        self._running_jobs.pop(job_id, None)
        return True

    async def update_config(
        self,
        tenant_id: str,
        job_id: str,
        *,
        message: str = "",
        config: dict[str, Any] | None = None,
        provider: str | None = None,
    ) -> AgentAsyncJob:
        """创建后通过自然语言或 JSON 修改任务配置（简报 + 编排）。"""
        job = self.get_job(tenant_id, job_id)
        if job is None:
            raise ValueError("任务不存在")
        if job.status == "running":
            raise ValueError("运行中的任务不可修改配置，请先取消或等待结束")
        if not (message or "").strip() and not config:
            raise ValueError("请提供 message（自然语言/JSON）或 config 字段")

        current = self._load_brief(job)
        new_brief, meta = await update_task_config(
            current,
            instruction=message,
            config=config,
            settings=self.settings,
            tenant_id=tenant_id,
            provider=provider or job.provider,
        )

        from app.services.agent_job_plan_service import _plan_from_brief

        result = job.result if isinstance(job.result, dict) else {}
        orch = _plan_from_brief(new_brief)
        orch = sync_orchestration_status(
            orch,
            job_stage=job.stage,
            job_status=job.status,
            job_result=result,
        )

        history = result.get("config_updates")
        if not isinstance(history, list):
            history = []
        history.append(meta)
        history = history[-30:]

        state = result.get("supervisor_state")
        if not isinstance(state, dict):
            state = {}
        state["config_revision"] = int(state.get("config_revision") or 0) + 1
        state["stale_cycles"] = 0
        state["_repeat_action_count"] = 0
        state.pop("crawl_failures", None)
        state.pop("crawl_done", None)
        state.pop("crawl_risk_blocked", None)
        state.pop("visible_crawl_done", None)
        state.pop("suspended", None)
        state.pop("resume_at", None)
        state.pop("wake_reason", None)

        job.message = brief_to_job_message(new_brief) if (message or "").strip() or config else job.message
        job.result = {
            **result,
            "orchestration": orch,
            "pipeline": orch.get("steps", []),
            "execution_mode": "supervisor",
            "config_updates": history,
            "supervisor_state": state,
        }
        if provider and provider in {"openai", "deepseek"}:
            job.provider = provider

        sandbox = TaskSandboxService(self.settings, tenant_id)
        sandbox_path = sandbox.sandbox_path(job_id)
        if sandbox_path.exists():
            (sandbox_path / "brief.md").write_text(new_brief.brief_md or "", encoding="utf-8")
            runtime_conn = sandbox.connect(job_id)
            if runtime_conn is not None:
                try:
                    runtime_conn.execute(
                        """
                        INSERT INTO task_kv (key, value, updated_at)
                        VALUES ('config_revision', ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                        """,
                        (str(state["config_revision"]), meta["at"]),
                    )
                    runtime_conn.commit()
                finally:
                    runtime_conn.close()

        self._apply_orchestration(job, self.settings)
        self.save(job)
        return job

    def destroy_sandbox(self, tenant_id: str, job_id: str, *, delete_job: bool = False) -> bool:
        """删除任务沙盒；可选同时删除 job 元数据。"""
        sandbox = TaskSandboxService(self.settings, tenant_id)
        removed = sandbox.destroy(job_id)
        if delete_job:
            path = self._path(tenant_id, job_id)
            if path.exists():
                path.unlink()
                return True
        return removed
