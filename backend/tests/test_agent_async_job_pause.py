from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJob, AgentAsyncJobService


@pytest.fixture()
def svc(tmp_path) -> AgentAsyncJobService:
    settings = Settings(storage_root=tmp_path / "storage")
    return AgentAsyncJobService(settings)


def _job(*, status: str = "queued", state: dict | None = None) -> AgentAsyncJob:
    now = datetime.now(timezone.utc)
    return AgentAsyncJob(
        job_id="pause-job",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status=status,
        created_at=now,
        updated_at=now,
        result={
            "orchestration": {
                "task_brief": {
                    "keyword": "ai获客",
                    "platform": "douyin",
                    "goals": {"target_leads": 5},
                }
            },
            "supervisor_state": state or {},
        },
    )


def test_pause_queued_job_marks_manual_suspend(svc: AgentAsyncJobService) -> None:
    job = _job(status="queued")
    svc.save(job)

    assert svc.pause("default", "pause-job") is True

    saved = svc.get_job("default", "pause-job")
    assert saved is not None
    assert saved.status == "pending"
    state = saved.result["supervisor_state"]
    assert state["suspended"] is True
    assert state["manual_pause"] is True
    assert state["wake_reason"] == "用户手动暂停任务"
    assert state["next_action"] == "点击「继续执行」从当前进度恢复运行"
    assert "resume_at" not in state


def test_pause_running_job_not_allowed_for_completed(svc: AgentAsyncJobService) -> None:
    job = _job(status="completed")
    svc.save(job)

    with pytest.raises(ValueError, match="仅运行中或排队中的任务可暂停"):
        svc.pause("default", "pause-job")


def test_resume_due_skips_manual_pause(svc: AgentAsyncJobService) -> None:
    job = _job(
        status="pending",
        state={
            "suspended": True,
            "manual_pause": True,
            "wake_reason": "用户手动暂停任务",
        },
    )
    assert AgentAsyncJobService._resume_due(job) is False
