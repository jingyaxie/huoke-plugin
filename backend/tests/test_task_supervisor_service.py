import pytest

from app.core.config import Settings
from app.services.task_brief_service import TaskBrief, _fallback_brief
from app.services.task_supervisor_service import TaskSupervisorService


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "storage")


def test_fallback_brief_from_json():
    raw = '{"keyword": "团餐配送", "platform": "douyin", "target_count": 30}'
    brief = _fallback_brief(raw)
    assert brief.keyword == "团餐配送"
    assert brief.platform == "douyin"
    assert brief.goals["target_leads"] == 30
    assert brief.goals["crawl_video_limit"] == 5
    assert "团餐配送" in brief.brief_md


def test_fallback_brief_accepts_crawl_video_limit_alias():
    raw = '{"keyword": "团餐配送", "platform": "douyin", "video_limit_per_batch": 12}'
    brief = _fallback_brief(raw)
    assert brief.goals["crawl_video_limit"] == 12


@pytest.mark.asyncio
async def test_heuristic_decide_crawl_first(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(
        keyword="团餐配送",
        goals={"target_leads": 50},
        platform="douyin",
    )
    decision = await svc._heuristic_decide(brief, {"progress": {"leads_collected": 0, "target_leads": 50}}, {})
    assert decision["action"] == "crawl_keyword"
    assert decision["params"]["keyword"] == "团餐配送"


@pytest.mark.asyncio
async def test_heuristic_decide_query_stats_after_crawl(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(
        keyword="团餐配送",
        goals={"target_leads": 50},
        platform="douyin",
    )
    decision = await svc._heuristic_decide(
        brief,
        {
            "progress": {"leads_collected": 0, "target_leads": 50},
            "interaction_stats": {
                "reply": {"count": 0, "limit": 30, "can_do": True},
            },
        },
        {"crawl_done": True, "comments_captured": 20},
    )
    assert decision["action"] == "query_stats"


def test_update_state_crawl_does_not_increment_leads(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(platform="douyin", goals={"target_leads": 50})
    state: dict = {"leads_collected": 0}
    svc._update_state(
        state,
        "crawl_keyword",
        {"status": "completed", "total_comments_captured": 40},
        brief,
        dry_run=True,
    )
    assert state.get("comments_captured") == 40
    assert state.get("leads_collected") == 0
    assert state.get("crawl_done") is True


@pytest.mark.asyncio
async def test_heuristic_decide_complete_when_target_met(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(goals={"target_leads": 10}, platform="douyin")
    decision = await svc._heuristic_decide(
        brief,
        {"progress": {"leads_collected": 12, "target_leads": 10}},
        {"leads_collected": 12},
    )
    assert decision["action"] == "complete"


@pytest.mark.asyncio
async def test_stale_cycles_force_suspend(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(
        keyword="团餐配送",
        goals={"target_leads": 50},
        platform="douyin",
    )
    exhausted = {
        "reply": {"count": 5, "limit": 5, "can_do": False},
        "dm": {"count": 3, "limit": 3, "can_do": False},
        "follow": {"count": 3, "limit": 3, "can_do": False},
    }

    async def stuck_decide(self, brief, snapshot, state):
        return {
            "action": "query_stats",
            "reasoning": "反复查台账",
            "params": {},
            "goal_progress": {"leads_collected": 11, "target_leads": 50},
        }

    svc._decide = stuck_decide.__get__(svc, TaskSupervisorService)  # type: ignore[method-assign]

    result = await svc.run(
        brief=brief,
        job_result={
            "supervisor_state": {
                "crawl_done": True,
                "leads_collected": 11,
                "simulated_stats": exhausted,
                "stale_cycles": 3,
            }
        },
        timeout_seconds=30,
        dry_run=True,
    )
    assert result["status"] == "suspended"
    assert "死循环" in (result.get("summary") or "")


@pytest.mark.asyncio
async def test_max_cycles_suspend_not_completed(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(keyword="团餐", goals={"target_leads": 100}, platform="douyin")

    async def always_reply(self, brief, snapshot, state):
        return {
            "action": "reply",
            "reasoning": "继续回复",
            "params": {},
            "goal_progress": {"leads_collected": state.get("leads_collected", 0), "target_leads": 100},
        }

    svc._decide = always_reply.__get__(svc, TaskSupervisorService)  # type: ignore[method-assign]

    result = await svc.run(
        brief=brief,
        job_result={"supervisor_state": {"crawl_done": True, "leads_collected": 5}},
        timeout_seconds=120,
        dry_run=True,
    )
    assert result["status"] == "suspended"
    assert len(result.get("supervisor_cycles") or []) <= 20


@pytest.mark.asyncio
async def test_round_mode_starts_next_round_after_target(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(
        keyword="团餐",
        goals={"target_leads": 2, "repeat_mode": "round", "round_target_count": 1, "max_rounds": 2},
        constraints={
            "repeat_mode": "round",
            "round_target_count": 1,
            "max_rounds": 2,
            "interval_min_sec": 1,
            "interval_max_sec": 1,
        },
        platform="douyin",
    )

    decisions = iter(
        [
            {"action": "reply", "reasoning": "第一轮触达", "params": {}, "goal_progress": {"leads_collected": 0, "target_leads": 1}},
            {"action": "reply", "reasoning": "第二轮先尝试触达，被守卫改为重新抓取", "params": {}, "goal_progress": {"leads_collected": 0, "target_leads": 1}},
            {"action": "reply", "reasoning": "第二轮同步配额后再触达", "params": {}, "goal_progress": {"leads_collected": 0, "target_leads": 1}},
            {"action": "reply", "reasoning": "第二轮触达", "params": {}, "goal_progress": {"leads_collected": 0, "target_leads": 1}},
        ]
    )

    async def decide(self, brief, snapshot, state):
        return next(decisions)

    async def resolve(self, decision, brief, state, *, action, snapshot_stats=None):
        return decision

    svc._decide = decide.__get__(svc, TaskSupervisorService)  # type: ignore[method-assign]
    svc._resolve_outreach_decision = resolve.__get__(svc, TaskSupervisorService)  # type: ignore[method-assign]

    result = await svc.run(
        brief=brief,
        job_result={"supervisor_state": {"crawl_done": True, "stats_synced": True}},
        timeout_seconds=120,
        dry_run=True,
    )
    state = result["supervisor_state"]
    assert result["status"] == "completed"
    assert state["completion_outcome"] == "max_rounds_reached"
    assert state["round_index"] == 2
    assert state["total_leads_collected"] == 2
    assert len(state["rounds"]) == 2


@pytest.mark.asyncio
async def test_normalize_decision_blocks_repeat_crawl(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(keyword="团餐配送", goals={"target_leads": 10}, platform="douyin")
    snapshot = {
        "progress": {"leads_collected": 0, "target_leads": 10},
        "interaction_stats": {"reply": {"count": 0, "limit": 5, "can_do": True}},
    }
    decision = await svc._normalize_decision(
        {"action": "crawl_keyword", "reasoning": "leads=0 重新抓取", "params": {"keyword": "团餐配送"}},
        brief,
        snapshot,
        {"crawl_done": True},
    )
    assert decision["action"] != "crawl_keyword"


@pytest.mark.asyncio
async def test_normalize_decision_blocks_reply_before_stats(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(keyword="团餐配送", goals={"target_leads": 10}, platform="douyin")
    decision = await svc._normalize_decision(
        {"action": "reply", "reasoning": "直接回复", "params": {"comment_id": "c1"}},
        brief,
        {"progress": {"leads_collected": 0, "target_leads": 10}},
        {"crawl_done": True},
    )
    assert decision["action"] == "query_stats"


def test_update_state_crawl_fails_without_structured_comments(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(platform="douyin", goals={"target_leads": 50})
    state: dict = {}
    svc._update_state(
        state,
        "crawl_keyword",
        {
            "status": "completed",
            "result": {"comments_collected": 1, "comments_by_video": []},
        },
        brief,
        dry_run=False,
    )
    assert state.get("crawl_done") is not True
    assert state.get("crawl_failures") == 1


def test_no_match_marks_source_exhausted(settings):
    svc = TaskSupervisorService(settings, "default", "douyin", "default")
    brief = TaskBrief(keyword="团餐配送", goals={"target_leads": 5}, platform="douyin")
    decision = svc._no_match_decision(
        brief,
        {"crawl_done": True, "crawl_search_exhausted": True, "leads_collected": 1},
        "已入库评论中无匹配待触达线索",
    )
    assert decision["action"] == "suspend"
    assert decision.get("completion_outcome") == "source_exhausted"
    assert "扫完" in decision["reasoning"]
