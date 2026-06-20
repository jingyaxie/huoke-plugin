import json
from datetime import datetime, timedelta, timezone

import pytest
import httpx

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJob, AgentAsyncJobService, _JobKey
from app.services.task_brief_service import TaskBrief


YINGXIAOYI_RAW = {
    "task_name": "深圳餐饮老板线索",
    "keyword": "团餐配送",
    "platform": "douyin",
    "region": "深圳",
    "video_publish_days": 7,
    "comment_days": 3,
    "target_count": 50,
}


@pytest.fixture
def job_service(tmp_path, monkeypatch):
    AgentAsyncJobService._instance = None
    settings = Settings(storage_root=tmp_path / "storage")
    svc = AgentAsyncJobService.get(settings)
    monkeypatch.setattr(svc, "_ensure_workers", lambda: None)

    async def mock_brief(message, **kwargs):
        return TaskBrief(
            title="深圳餐饮老板线索",
            brief_md="# 深圳餐饮老板线索",
            platform="douyin",
            keyword="团餐配送",
            region="深圳",
            goals={"target_leads": 50, "comment_days": 3},
            reasoning="mock",
            confidence=0.9,
            llm_available=True,
            llm_fallback=False,
        )

    monkeypatch.setattr(
        "app.services.agent_job_plan_service.generate_task_brief",
        mock_brief,
    )
    yield svc, settings
    for worker in svc._workers:
        worker.cancel()
    AgentAsyncJobService._instance = None


def test_account_key_includes_platform(job_service):
    svc, _settings = job_service
    douyin = svc._account_key("tenant", "douyin", "default")
    xhs = svc._account_key("tenant", "xiaohongshu", "default")
    assert douyin != xhs


def test_defer_only_blocks_same_platform_account(job_service):
    svc, _settings = job_service
    svc._account_active[svc._account_key("default", "douyin", "default")] = "job-douyin"
    xhs_job = AgentAsyncJob(
        job_id="job-xhs",
        tenant_id="default",
        platform="xiaohongshu",
        account_id="default",
        message="xhs",
    )
    douyin_job = AgentAsyncJob(
        job_id="job-douyin-2",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="douyin",
    )
    assert svc._defer_job_for_account_busy(xhs_job) is False
    assert svc._defer_job_for_account_busy(douyin_job) is True


@pytest.mark.asyncio
async def test_submit_marks_supervisor_mode(job_service):
    svc, _settings = job_service
    message = json.dumps(YINGXIAOYI_RAW, ensure_ascii=False)
    job = await svc.submit_async(
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message=message,
        auto_execute=False,
    )
    assert job.result["execution_mode"] == "supervisor"
    assert job.result["orchestration"]["source"] == "supervisor"
    assert job.result["orchestration"]["task_brief"]["keyword"] == "团餐配送"
    assert job.result.get("sandbox", {}).get("job_id") == job.job_id
    assert "leads" in (job.result.get("sandbox", {}).get("tables") or [])


@pytest.mark.asyncio
async def test_submit_accepts_structured_round_config(job_service):
    svc, _settings = job_service
    job = await svc.submit_async(
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="深圳团餐循环任务",
        auto_execute=False,
        config={
            "keyword": "团餐配送",
            "target_count": 80,
            "repeat_mode": "round",
            "round_target_count": 80,
            "max_rounds": 2,
        },
    )
    brief = job.result["orchestration"]["task_brief"]
    assert brief["goals"]["repeat_mode"] == "round"
    assert brief["goals"]["round_target_count"] == 80
    assert brief["goals"]["max_rounds"] == 2
    assert job.result["orchestration"]["input_summary"]["repeat_mode"] == "round"


@pytest.mark.asyncio
async def test_run_completes_via_supervisor(job_service, monkeypatch):
    svc, settings = job_service
    message = json.dumps(YINGXIAOYI_RAW, ensure_ascii=False)

    async def mock_run(self, **kwargs):
        return {
            **kwargs["job_result"],
            "status": "completed",
            "summary": "mock supervisor done",
            "supervisor_cycles": [
                {
                    "cycle": 1,
                    "action": "crawl_keyword",
                    "reasoning": "首轮抓取",
                    "ok": True,
                    "result_summary": "抓取完成",
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.agent_async_job_service.TaskSupervisorService.run",
        mock_run,
    )

    job = await svc.submit_async(
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message=message,
        auto_execute=False,
    )
    await svc._run_job(_JobKey(tenant_id=job.tenant_id, job_id=job.job_id), settings)

    loaded = svc.get_job(job.tenant_id, job.job_id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.result["execution_mode"] == "supervisor"
    assert loaded.result["summary"] == "mock supervisor done"
    assert len(loaded.result.get("supervisor_cycles") or []) == 1


@pytest.mark.asyncio
async def test_restart_cancelled_job(job_service):
    svc, _settings = job_service
    job = await svc.submit_async(
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="关键词「团餐配送」",
        auto_execute=False,
    )
    svc.cancel("default", job.job_id)
    restarted = svc.execute("default", job.job_id)
    assert restarted is not None
    assert restarted.status == "queued"
    loaded = svc.get_job("default", job.job_id)
    assert loaded is not None
    assert loaded.stage == "observe"
    events = loaded.result.get("progress_events") or []
    assert any(e.get("type") == "restart" for e in events)


def test_execute_clears_suspend_gate_for_pending_job(job_service):
    svc, _settings = job_service

    pending = AgentAsyncJob(
        job_id="test-suspend-manual",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="pending",
        result={
            "execution_mode": "supervisor",
            "supervisor_state": {
                "suspended": True,
                "resume_at": "2099-01-01T00:00:00+00:00",
                "wake_reason": "配额用尽",
                "crawl_done": True,
                "leads_collected": 3,
            },
        },
    )
    svc.save(pending)
    restarted = svc.execute("default", pending.job_id)
    assert restarted is not None
    assert restarted.status == "queued"
    state = restarted.result.get("supervisor_state") or {}
    assert not state.get("suspended")
    assert not state.get("resume_at")
    assert state.get("crawl_done") is True
    assert state.get("leads_collected") == 3
    events = restarted.result.get("progress_events") or []
    assert any(e.get("type") == "manual_resume" for e in events)


def test_delete_job_removes_metadata(job_service):
    svc, _settings = job_service

    row = AgentAsyncJob(
        job_id="test-delete-1",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="cancelled",
        result={"execution_mode": "supervisor"},
    )
    svc.save(row)
    assert svc.delete_job("default", row.job_id) is True
    assert svc.get_job("default", row.job_id) is None


def test_delete_running_job_rejected(job_service):
    svc, _settings = job_service

    row = AgentAsyncJob(
        job_id="test-delete-running",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="running",
        result={"execution_mode": "supervisor"},
    )
    svc.save(row)
    with pytest.raises(ValueError, match="取消"):
        svc.delete_job("default", row.job_id)
    assert svc.get_job("default", row.job_id) is not None


def test_save_writes_readable_json_atomically(job_service):
    svc, _settings = job_service
    row = AgentAsyncJob(
        job_id="test-atomic-save",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="pending",
    )
    svc.save(row)
    path = svc._path("default", row.job_id)
    assert json.loads(path.read_text(encoding="utf-8"))["job_id"] == row.job_id
    assert not list(path.parent.glob("*.tmp"))


def test_recover_active_jobs_on_startup_requeues(job_service):
    svc, _settings = job_service
    for status in ("queued", "running", "retrying"):
        svc.save(
            AgentAsyncJob(
                job_id=f"recover-{status}",
                tenant_id="default",
                platform="douyin",
                account_id="default",
                message="test",
                status=status,
            )
        )
    svc._recover_active_jobs_on_startup()
    assert svc._queue.qsize() == 3
    for status in ("queued", "running", "retrying"):
        loaded = svc.get_job("default", f"recover-{status}")
        assert loaded is not None
        assert loaded.status == "queued"


def test_enqueue_due_pending_jobs(job_service):
    svc, _settings = job_service
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    svc.save(
        AgentAsyncJob(
            job_id="due-pending",
            tenant_id="default",
            platform="douyin",
            account_id="default",
            message="test",
            status="pending",
            result={"supervisor_state": {"suspended": True, "resume_at": past}},
        )
    )
    svc.save(
        AgentAsyncJob(
            job_id="future-pending",
            tenant_id="default",
            platform="douyin",
            account_id="default",
            message="test",
            status="pending",
            result={"supervisor_state": {"suspended": True, "resume_at": future}},
        )
    )
    assert svc.enqueue_due_pending_jobs() == 1
    assert svc.get_job("default", "due-pending").status == "queued"
    assert svc.get_job("default", "future-pending").status == "pending"


@pytest.mark.asyncio
async def test_webhook_failure_does_not_change_job_status(job_service, monkeypatch):
    svc, _settings = job_service
    job = AgentAsyncJob(
        job_id="webhook-fail",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="completed",
        webhook_url="https://example.invalid/hook",
    )

    async def boom(self, *args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    await svc._post_webhook(job)
    loaded = svc.get_job("default", job.job_id)
    assert loaded is not None
    assert loaded.status == "completed"
    events = loaded.result.get("progress_events") or []
    assert any(e.get("type") == "webhook_error" for e in events)
