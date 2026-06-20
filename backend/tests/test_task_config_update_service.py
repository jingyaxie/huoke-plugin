import json

import pytest

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJobService
from app.services.task_brief_service import TaskBrief
from app.services.task_config_update_service import (
    apply_patch_to_brief,
    apply_rule_based_nl_patch,
    brief_to_job_message,
    extract_structured_patch,
    update_task_config,
)


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "storage")


@pytest.fixture
def brief():
    return TaskBrief(
        title="团餐任务",
        keyword="团餐配送",
        platform="douyin",
        goals={"target_leads": 50, "comment_days": 3},
        constraints={"daily_dm_limit": 3, "outreach_priority": ["reply", "dm", "follow"]},
        brief_md="# 团餐任务\n\n## 目标\n50 条",
    )


def test_extract_json_patch_goals():
    patch = extract_structured_patch('{"goals": {"target_leads": 100}}')
    assert patch is not None
    assert patch["goals"]["target_leads"] == 100


def test_extract_flat_json_payload():
    patch = extract_structured_patch(
        json.dumps({"keyword": "企业团餐", "target_count": 80, "platform": "douyin", "video_limit": 7})
    )
    assert patch["keyword"] == "企业团餐"
    assert patch["goals"]["target_leads"] == 80
    assert patch["goals"]["crawl_video_limit"] == 7


def test_extract_round_mode_payload():
    patch = extract_structured_patch(
        json.dumps(
            {
                "keyword": "企业团餐",
                "repeat_mode": "round",
                "round_target_count": 80,
                "max_rounds": 3,
            }
        )
    )
    assert patch["goals"]["repeat_mode"] == "round"
    assert patch["goals"]["round_target_count"] == 80
    assert patch["goals"]["max_rounds"] == 3
    assert patch["constraints"]["repeat_mode"] == "round"


def test_rule_based_nl_target_and_priority(brief):
    updated, changes = apply_rule_based_nl_patch(brief, "把目标改成100条，私信优先")
    assert updated.goals["target_leads"] == 100
    assert updated.constraints["outreach_priority"] == ["dm", "reply", "follow"]
    assert any("100" in c for c in changes)


@pytest.mark.asyncio
async def test_update_task_config_structured(settings, brief):
    new_brief, meta = await update_task_config(
        brief,
        config={"constraints": {"daily_dm_limit": 10}},
        settings=settings,
        tenant_id="default",
    )
    assert new_brief.constraints["daily_dm_limit"] == 10
    assert new_brief.constraints["outreach_priority"] == ["reply", "dm", "follow"]
    assert meta["had_structured_config"] is True


@pytest.mark.asyncio
async def test_update_task_config_json_message(settings, brief):
    new_brief, meta = await update_task_config(
        brief,
        instruction='{"keyword": "写字楼团餐", "target_count": 30}',
        settings=settings,
        tenant_id="default",
    )
    assert new_brief.keyword == "写字楼团餐"
    assert new_brief.goals["target_leads"] == 30
    assert "json_instruction_patch" in meta["changes"]


def test_brief_to_job_message_roundtrip(brief):
    brief.goals["crawl_video_limit"] = 6
    brief.goals["repeat_mode"] = "round"
    brief.goals["round_target_count"] = 50
    brief.goals["max_rounds"] = 2
    text = brief_to_job_message(brief)
    data = json.loads(text)
    assert data["keyword"] == "团餐配送"
    assert data["target_count"] == 50
    assert data["crawl_video_limit"] == 6
    assert data["repeat_mode"] == "round"
    assert data["round_target_count"] == 50
    assert data["max_rounds"] == 2


@pytest.mark.asyncio
async def test_agent_service_update_config(settings, brief):
    svc = AgentAsyncJobService(settings)
    job = await svc.submit_async(
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="关键词「团餐配送」目标50条",
        auto_execute=False,
    )
    updated = await svc.update_config(
        "default",
        job.job_id,
        message="目标改成80条，私信优先",
    )
    orch = updated.result.get("orchestration") or {}
    task_brief = orch.get("task_brief") or {}
    assert task_brief.get("goals", {}).get("target_leads") == 80
    assert task_brief.get("constraints", {}).get("outreach_priority") == ["dm", "reply", "follow"]
    history = updated.result.get("config_updates") or []
    assert len(history) >= 1
