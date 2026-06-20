import asyncio
import json

import pytest

from app.core.config import Settings
from app.services.agent_job_plan_service import _plan_from_brief, build_orchestration_plan, sync_orchestration_status
from app.services.supervisor_outreach import outreach_interval_from_brief
from app.services.task_brief_service import TaskBrief


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "storage")


@pytest.mark.asyncio
async def test_build_orchestration_plan_supervisor_mode(settings, monkeypatch):
    async def mock_brief(message, **kwargs):
        from app.services.task_brief_service import _finalize_brief
        return _finalize_brief(TaskBrief(
            title="深圳餐饮线索",
            brief_md="# 深圳餐饮线索\n\n## 目标\n抓取",
            platform="douyin",
            keyword="团餐配送",
            region="深圳",
            goals={"target_leads": 50, "comment_days": 3},
            reasoning="mock brief",
            confidence=0.9,
            llm_available=True,
            llm_fallback=False,
        ))

    monkeypatch.setattr(
        "app.services.agent_job_plan_service.generate_task_brief",
        mock_brief,
    )
    plan = await build_orchestration_plan(
        json.dumps({"keyword": "团餐配送", "platform": "douyin"}, ensure_ascii=False),
        settings=settings,
        tenant_id="default",
    )
    assert plan["execution_mode"] == "skill_flow"
    assert plan["source"] == "supervisor"
    assert plan["steps"][0]["id"] == "understand"
    assert plan["task_brief"]["keyword"] == "团餐配送"
    assert plan["task_brief"].get("allowed_skills")
    assert "Skill 白名单" in plan["task_brief"].get("brief_md", "")
    assert plan["input_summary"]["keyword"] == "团餐配送"


@pytest.mark.asyncio
async def test_build_orchestration_plan_fallback_brief(settings, monkeypatch):
    async def mock_brief(message, **kwargs):
        from app.services.task_brief_service import _fallback_brief
        return _fallback_brief(message)

    monkeypatch.setattr(
        "app.services.agent_job_plan_service.generate_task_brief",
        mock_brief,
    )
    plan = await build_orchestration_plan(
        "帮我抓取深圳团餐配送相关评论线索",
        settings=settings,
        tenant_id="default",
    )
    assert plan["execution_mode"] == "skill_flow"
    assert plan["source"] == "supervisor"
    assert plan["llm_fallback"] is True
    assert plan["task_brief"]["brief_md"]


def test_build_orchestration_plan_skill_flow_plan_driven(settings, monkeypatch):
    async def mock_brief(message, **kwargs):
        from app.services.agent_strategy.registry import SKILL_FLOW_DOUYIN
        from app.services.task_brief_service import _finalize_brief

        return _finalize_brief(
            TaskBrief(
                title="计划驱动测试",
                brief_md="# 测试",
                platform="douyin",
                keyword="团餐配送",
                goals={"target_leads": 20, "comment_days": 3},
                reasoning="mock",
                confidence=0.9,
                llm_available=True,
                llm_fallback=False,
            ),
            agent_strategy=SKILL_FLOW_DOUYIN.id,
        )

    monkeypatch.setattr(
        "app.services.agent_job_plan_service.generate_task_brief",
        mock_brief,
    )
    message = json.dumps(
        {
            "keyword": "团餐配送",
            "platform": "douyin",
            "agent_strategy": "skill-flow-douyin",
            "evaluation": {
                "accept_description": "咨询团餐、配送价格或合作",
                "reject_signals": ["招聘"],
            },
            "outreach_strategy": {
                "dm_template": "您好，方便聊聊吗？",
                "priority": ["reply", "dm", "follow"],
            },
        },
        ensure_ascii=False,
    )
    plan = asyncio.run(
        build_orchestration_plan(message, settings=settings, tenant_id="default")
    )
    assert plan["execution_mode"] == "skill_flow"
    assert plan["template_name"] == "计划驱动（Skill 分步）"
    plan_step = next(s for s in plan["steps"] if s["id"] == "plan")
    assert "不用 LLM" in plan_step["action"]
    assert plan_step.get("sub_steps")
    assert plan_step["sub_steps"][0]["action"] == "crawl_keyword"
    assert plan_step["sub_steps"][1]["action"] == "evaluate_leads"
    draft = plan["task_brief"]["constraints"].get("evaluation_draft") or {}
    assert "团餐" in str(draft.get("accept_description") or "") or draft.get("reject_signals")
    assert plan["task_brief"]["constraints"].get("dm_template") == "您好，方便聊聊吗？"
    assert plan["tactical_plan"]["pipeline"] == "skill_flow"
    dream = next(s for s in plan["steps"] if s["id"] == "dream")
    assert dream["status"] == "skipped"


def test_enrich_brief_normalizes_interval_aliases():
    from app.services.task_brief_service import enrich_brief_from_task_payload

    brief = TaskBrief(platform="douyin", keyword="淋浴房")
    enriched, _ = enrich_brief_from_task_payload(
        brief,
        {"constraints": {"interval_min": 10, "interval_max": 30}},
    )
    assert enriched.constraints["interval_min_sec"] == 10
    assert enriched.constraints["interval_max_sec"] == 30
    assert outreach_interval_from_brief(enriched) == (10, 30)


def test_enrich_brief_from_task_payload():
    from app.services.task_brief_service import enrich_brief_from_task_payload

    brief = TaskBrief(platform="douyin", keyword="团餐")
    enriched, unmapped = enrich_brief_from_task_payload(
        brief,
        {
            "evaluation": {"accept_description": "咨询团餐", "reject_signals": ["广告"]},
            "outreach_strategy": {"dm_template": "测试模板"},
            "unknown_field": 1,
        },
    )
    draft = enriched.constraints.get("evaluation_draft") or {}
    assert "团餐" in str(draft.get("accept_description") or "")
    assert enriched.constraints["dm_template"] == "测试模板"
    assert "reply_template" not in enriched.constraints
    assert "unknown_field" in unmapped


def test_enrich_brief_does_not_report_flat_consumed_fields():
    from app.services.task_brief_service import enrich_brief_from_task_payload

    brief = TaskBrief(platform="douyin", keyword="团餐")
    enriched, unmapped = enrich_brief_from_task_payload(
        brief,
        {
            "target_count": 80,
            "success_criteria": "累计触达80个线索",
        },
    )
    assert enriched.goals["target_leads"] == 80
    assert enriched.success_criteria == "累计触达80个线索"
    assert unmapped == []


def test_plan_input_summary_includes_round_loop():
    brief = TaskBrief(
        platform="douyin",
        keyword="团餐",
        goals={"target_leads": 80, "repeat_mode": "round", "round_target_count": 80, "max_rounds": 3},
        constraints={"repeat_mode": "round", "round_target_count": 80, "max_rounds": 3},
    )
    plan = _plan_from_brief(brief)
    summary = plan["input_summary"]
    assert summary["repeat_mode"] == "round"
    assert summary["round_target_count"] == 80
    assert summary["max_rounds"] == 3


def test_sync_orchestration_status_goal_reached_note():
    plan = {
        "execution_mode": "supervisor",
        "steps": [{"id": "understand", "stage": "understand", "status": "completed"}],
    }
    synced = sync_orchestration_status(
        plan,
        job_stage="dream",
        job_status="completed",
        job_result={
            "completion_outcome": "goal_reached",
            "data_snapshot": {"progress": {"leads_collected": 10, "target_leads": 10}},
        },
    )
    assert "目标线索已达成" in synced["execution_note"]


def test_sync_orchestration_status_plan_incomplete_note():
    plan = {
        "execution_mode": "supervisor",
        "steps": [{"id": "understand", "stage": "understand", "status": "completed"}],
    }
    synced = sync_orchestration_status(
        plan,
        job_stage="dream",
        job_status="pending",
        job_result={
            "completion_outcome": "plan_incomplete",
            "supervisor_state": {"suspended": True},
            "data_snapshot": {"progress": {"leads_collected": 0, "target_leads": 10}},
        },
    )
    assert "已暂停" in synced["execution_note"]


def test_sync_orchestration_status_marks_supervisor_running():
    plan = {
        "execution_mode": "supervisor",
        "steps": [
            {"id": "understand", "stage": "understand", "status": "completed"},
            {"id": "observe", "stage": "observe", "status": "pending"},
            {"id": "plan", "stage": "plan", "status": "pending"},
        ],
    }
    synced = sync_orchestration_status(plan, job_stage="plan", job_status="running")
    assert synced["steps"][0]["status"] == "completed"
    assert synced["steps"][1]["status"] == "completed"
    assert synced["steps"][2]["status"] == "running"


def test_sync_orchestration_status_suspended_pending_shows_act_failed():
    plan = {
        "execution_mode": "skill_flow",
        "steps": [
            {"id": "understand", "stage": "understand", "status": "completed"},
            {"id": "observe", "stage": "observe", "status": "completed"},
            {"id": "plan", "stage": "plan", "status": "completed"},
            {"id": "act", "stage": "act", "status": "running"},
            {"id": "track", "stage": "track", "status": "completed"},
            {"id": "dream", "stage": "dream", "status": "running", "status_orig": "skipped"},
        ],
    }
    plan["steps"][5]["status"] = "skipped"
    synced = sync_orchestration_status(
        plan,
        job_stage="act",
        job_status="pending",
        job_result={
            "supervisor_state": {
                "suspended": True,
                "crawl_failures": 1,
                "wake_reason": "抓取失败，挂起避免重复搜索触发风控",
            },
        },
    )
    by_id = {s["id"]: s for s in synced["steps"]}
    assert by_id["act"]["status"] == "failed"
    assert by_id["track"]["status"] == "pending"
    assert by_id["dream"]["status"] == "skipped"
    assert "挂起" in synced["execution_note"]
