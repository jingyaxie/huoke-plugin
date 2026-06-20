from __future__ import annotations

import pytest

from app.schemas.agent_experience import AgentExperienceCreate
from app.schemas.agent_profile import AgentProfileOut
from app.services.agent_experience_store import AgentExperienceStore
from app.services.agent_profile_store import AgentProfileStore
from app.services.agent_subagent import build_subagent_system_prompt


def _profile(**kwargs) -> AgentProfileOut:
    base = {
        "id": "test",
        "name": "测试",
        "description": "",
        "system_prompt": "",
        "inherit_base_prompt": True,
        "inherit_workflow_prompt": True,
        "exclude_rule_ids": [],
        "inherit_experience_prompt": True,
        "skill_ids": [],
        "platforms": [],
        "enabled": True,
        "scope": "tenant",
    }
    base.update(kwargs)
    return AgentProfileOut.model_validate(base)


def test_pipeline_recovery_profile_resolve():
    profile = AgentProfileStore.pipeline_recovery_profile()
    assert profile.id == "pipeline-recovery"
    assert profile.inherit_workflow_prompt is True
    assert "Pipeline Recovery" in profile.system_prompt


def test_subagent_prompt_follows_profile():
    custom = _profile(
        id="custom-douyin-task",
        inherit_workflow_prompt=False,
        system_prompt="只 invoke 指定 Skill。",
    )
    prompt = build_subagent_system_prompt(custom)
    assert "只 invoke 指定 Skill" in prompt
    assert "禁止 browser_click" not in prompt

    daily = _profile(inherit_workflow_prompt=True)
    prompt_daily = build_subagent_system_prompt(daily)
    assert "禁止 browser_click" in prompt_daily


@pytest.fixture()
def experience_store(tmp_path):
    from app.core.config import Settings

    return AgentExperienceStore(Settings(storage_root=tmp_path / "storage"))


def test_experience_filtered_by_agent_profile(experience_store):
    experience_store.create(
        "default",
        AgentExperienceCreate(
            id="exp-global",
            title="全局",
            task_keywords=["淋浴房"],
            outcome="success",
            lesson="全局经验",
            platform="douyin",
        ),
    )
    experience_store.create(
        "default",
        AgentExperienceCreate(
            id="exp-social",
            title="专用",
            task_keywords=["淋浴房", "专用档案"],
            outcome="success",
            lesson="专用经验",
            platform="douyin",
            agent_profile_id="custom-douyin-task",
        ),
    )
    items = experience_store.retrieve_for_task(
        "default",
        query="淋浴房获客",
        platform="douyin",
        limit=5,
        agent_profile_id="custom-douyin-task",
    )
    ids = {item.id for item in items}
    assert "exp-global" in ids
    assert "exp-social" in ids

    daily_items = experience_store.retrieve_for_task(
        "default",
        query="淋浴房获客",
        platform="douyin",
        limit=5,
        agent_profile_id="task-douyin-skill-flow",
    )
    daily_ids = {item.id for item in daily_items}
    assert "exp-global" in daily_ids
    assert "exp-social" not in daily_ids
