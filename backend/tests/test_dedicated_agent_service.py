from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.agent_strategy.registry import SKILL_FLOW_DOUYIN
from app.services.dedicated_agent.constants import (
    GENERAL_AGENT_PROFILE_ID,
    is_task_dedicated_profile,
    platform_task_profile_id,
)
from app.services.dedicated_agent.service import DedicatedAgentService
from app.services.task_brief_service import TaskBrief


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.storage_root = tmp_path
    return s


def test_platform_task_profile_id_uses_default_strategy():
    assert platform_task_profile_id("douyin") == "task-douyin-skill-flow"
    assert is_task_dedicated_profile("task-douyin-skill-flow")
    assert not is_task_dedicated_profile("default")


def test_chat_profile_blocks_task_dedicated():
    assert DedicatedAgentService.resolve_chat_profile_id("task-douyin-skill-flow") == GENERAL_AGENT_PROFILE_ID
    assert DedicatedAgentService.resolve_chat_profile_id(None) == GENERAL_AGENT_PROFILE_ID
    assert DedicatedAgentService.resolve_chat_profile_id("my-custom") == "my-custom"


def test_attach_dedicated_agent_to_plan_skill_flow(settings):
    brief = TaskBrief(
        title="测试",
        platform="douyin",
        keyword="团餐",
        agent_strategy=SKILL_FLOW_DOUYIN.id,
        allowed_skills=[{"skill_id": "douyin-keyword-comments", "supervisor_action": "crawl_keyword"}],
    )
    plan: dict = {"execution_note": "note"}
    svc = DedicatedAgentService(settings)
    meta = svc.attach_to_orchestration_plan("default", brief, plan)
    assert meta["profile_id"] == "task-douyin-skill-flow"
    assert meta["strategy_id"] == SKILL_FLOW_DOUYIN.id
    assert "douyin-keyword-comments" in meta["skill_ids"]
    assert plan["dedicated_agent"]["kind"] == "platform_task"


def test_attach_dedicated_agent_skill_flow(settings):
    brief = TaskBrief(
        title="测试",
        platform="douyin",
        keyword="团餐",
        agent_strategy=SKILL_FLOW_DOUYIN.id,
    )
    plan: dict = {}
    meta = DedicatedAgentService(settings).attach_to_orchestration_plan("default", brief, plan)
    assert meta["profile_id"] == "task-douyin-skill-flow"
    assert meta["execution_mode"] == "skill_flow"
    assert "douyin-keyword-comments" in meta["skill_ids"]


def test_strategy_profile_builtin(settings):
    from app.services.agent_profile_store import AgentProfileStore

    store = AgentProfileStore(settings)
    skill_flow_profile = store.get("default", "task-douyin-skill-flow")
    assert skill_flow_profile is not None
    assert "douyin-keyword-comments" in skill_flow_profile.skill_ids
