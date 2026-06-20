from __future__ import annotations

from app.schemas.agent_profile import AgentProfileOut
from app.services.agent_service import (
    RUNTIME_KERNEL_PROMPT,
    STANDARD_WORKFLOW_PROMPT,
    _build_system_prompt,
)


def _profile(**kwargs) -> AgentProfileOut:
    base = {
        "id": "test",
        "name": "测试档案",
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


def test_default_profile_includes_runtime_and_workflow():
    prompt = _build_system_prompt("", "", "", "agent", _profile())
    assert RUNTIME_KERNEL_PROMPT.strip() in prompt
    assert STANDARD_WORKFLOW_PROMPT.strip() in prompt
    assert "douyin-keyword-comments" in prompt


def test_custom_profile_skips_workflow():
    prompt = _build_system_prompt(
        "",
        "",
        "",
        "agent",
        _profile(
            id="custom-douyin-task",
            inherit_workflow_prompt=False,
            system_prompt="只 invoke 指定 Skill。",
        ),
    )
    assert RUNTIME_KERNEL_PROMPT.strip() in prompt
    assert "douyin-keyword-comments" not in prompt
    assert "只 invoke 指定 Skill" in prompt


def test_custom_only_profile_without_kernel():
    prompt = _build_system_prompt(
        "",
        "",
        "",
        "agent",
        _profile(
            inherit_base_prompt=False,
            inherit_workflow_prompt=False,
            system_prompt="完全自定义提示。",
        ),
    )
    assert prompt == "完全自定义提示。"


def test_rules_prompt_appended_when_provided():
    prompt = _build_system_prompt(
        "",
        "### 租户规则\n禁止手工搜索",
        "",
        "agent",
        _profile(inherit_workflow_prompt=False),
    )
    assert "租户规则" in prompt
    assert "禁止手工搜索" in prompt
