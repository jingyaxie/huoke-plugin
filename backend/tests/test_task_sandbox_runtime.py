import pytest

from app.core.config import Settings
from app.services.task_brief_service import TaskBrief
from app.services.task_sandbox_runtime import TaskSandboxRuntime
from app.services.task_sandbox_service import TaskSandboxService
from app.services.task_schema_service import DEFAULT_LEAD_TASK_SCHEMA
from app.services.task_supervisor_service import TaskSupervisorService


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "storage")


@pytest.fixture
def brief():
    return TaskBrief(
        keyword="团餐配送",
        goals={"target_leads": 5, "mock_crawl_batch": 10},
        constraints={"outreach_priority": ["dm", "reply", "follow"]},
        platform="douyin",
    )


async def _provision(settings, job_id: str, brief: TaskBrief) -> None:
    svc = TaskSandboxService(settings, "default")
    await svc.provision(job_id=job_id, brief=brief, schema=DEFAULT_LEAD_TASK_SCHEMA)


@pytest.mark.asyncio
async def test_runtime_loads_helpers_and_records_crawl(settings, brief):
    job_id = "job-rt-1"
    await _provision(settings, job_id, brief)
    runtime = TaskSandboxRuntime(settings, "default", job_id)
    helpers = runtime.load_helpers()
    assert helpers is not None
    assert hasattr(helpers, "match_comment")
    assert hasattr(helpers, "next_outreach_action")

    runtime.record_action(
        action="crawl_keyword",
        skill_result={"status": "completed", "total_comments_captured": 8, "videos_processed": 2},
        brief=brief,
        params={"keyword": "团餐配送", "video_limit": 2},
        dry_run=True,
    )
    summary = runtime.get_summary()
    assert summary["crawl_batches"] == 1
    assert summary["leads_total"] >= 1


@pytest.mark.asyncio
async def test_runtime_records_outreach_and_syncs_state(settings, brief):
    job_id = "job-rt-2"
    await _provision(settings, job_id, brief)
    runtime = TaskSandboxRuntime(settings, "default", job_id)
    runtime.record_action(
        action="reply",
        skill_result={
            "status": "completed",
            "comment_id": "cmt-1",
            "target_user_id": "uid-1",
            "reply_text": "你好",
        },
        brief=brief,
        dry_run=True,
    )
    state: dict = {}
    runtime.sync_supervisor_state(state)
    assert state["leads_collected"] == 1

    summary = runtime.get_summary()
    assert summary["outreach_ok"] == 1


@pytest.mark.asyncio
async def test_runtime_zero_comment_crawl_does_not_mark_done(settings, brief):
    job_id = "job-rt-zero"
    await _provision(settings, job_id, brief)
    runtime = TaskSandboxRuntime(settings, "default", job_id)
    runtime.record_action(
        action="crawl_keyword",
        skill_result={"status": "completed", "total_comments_captured": 0, "videos_processed": 1},
        brief=brief,
        params={"keyword": "团餐配送", "video_limit": 1},
        dry_run=False,
    )
    summary = runtime.get_summary()
    assert summary["crawl_batches"] == 1
    assert summary["crawl_comments_total"] == 0
    state: dict = {}
    runtime.sync_supervisor_state(state)
    assert "crawl_done" not in state


@pytest.mark.asyncio
async def test_runtime_reset_crawl_progress_clears_kv(settings, brief):
    job_id = "job-rt-reset"
    await _provision(settings, job_id, brief)
    runtime = TaskSandboxRuntime(settings, "default", job_id)
    runtime.record_action(
        action="crawl_keyword",
        skill_result={"status": "completed", "total_comments_captured": 5, "videos_processed": 1},
        brief=brief,
        params={"keyword": "团餐配送", "video_limit": 1},
        dry_run=True,
    )
    state: dict = {}
    runtime.sync_supervisor_state(state)
    assert state.get("crawl_done") is True
    runtime.reset_crawl_progress()
    state = {}
    runtime.sync_supervisor_state(state)
    assert "crawl_done" not in state


@pytest.mark.asyncio
async def test_helpers_suggest_dm_first(settings, brief):
    job_id = "job-rt-3"
    await _provision(settings, job_id, brief)
    runtime = TaskSandboxRuntime(settings, "default", job_id)
    stats = {
        "reply": {"count": 0, "limit": 5, "can_do": True},
        "dm": {"count": 0, "limit": 3, "can_do": True},
        "follow": {"count": 0, "limit": 3, "can_do": True},
    }
    assert runtime.suggest_outreach_action(stats, brief) == "dm"


@pytest.mark.asyncio
async def test_supervisor_dry_run_writes_sandbox(settings, brief):
    job_id = "job-sup-sbx"
    await _provision(settings, job_id, brief)
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief.agent_strategy = None
    brief.goals["supervisor_plan_only"] = False

    async def crawl_then_reply(self, b, snapshot, state):
        if not state.get("crawl_done"):
            return {
                "action": "crawl_keyword",
                "reasoning": "抓取",
                "params": {"keyword": "团餐配送", "video_limit": 2},
                "goal_progress": {"leads_collected": 0, "target_leads": 5},
            }
        if not state.get("stats_checked"):
            return {
                "action": "query_stats",
                "reasoning": "触达前查配额",
                "params": {},
                "goal_progress": {"leads_collected": state.get("leads_collected", 0), "target_leads": 5},
            }
        return {
            "action": "reply",
            "reasoning": "触达",
            "params": {},
            "goal_progress": {"leads_collected": state.get("leads_collected", 0), "target_leads": 5},
        }

    svc._decide = crawl_then_reply.__get__(svc, TaskSupervisorService)  # type: ignore[method-assign]

    result = await svc.run(
        brief=brief,
        job_result={
            "sandbox": {"job_id": job_id},
            "supervisor_state": {
                "simulated_stats": {
                    "reply": {"count": 0, "limit": 5, "can_do": True},
                    "dm": {"count": 0, "limit": 3, "can_do": True},
                    "follow": {"count": 0, "limit": 3, "can_do": True},
                }
            },
        },
        job_id=job_id,
        timeout_seconds=60,
        dry_run=True,
    )
    runtime = TaskSandboxRuntime(settings, "default", job_id)
    summary = runtime.get_summary()
    assert summary["crawl_batches"] >= 1
    assert summary["leads_total"] >= 1
    assert result["status"] == "suspended"
    assert "数据库会话" in (result.get("summary") or "")
