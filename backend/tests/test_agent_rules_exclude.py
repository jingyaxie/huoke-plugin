from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.agent_rule_store import AgentRuleStore


@pytest.fixture()
def rule_store(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage")
    return AgentRuleStore(settings)


def test_build_rules_prompt_excludes_by_profile(rule_store):
    prompt_all = rule_store.build_rules_prompt("default", "douyin")
    prompt_filtered = rule_store.build_rules_prompt(
        "default",
        "douyin",
        exclude_rule_ids=["douyin-platform"],
    )
    assert "抖音平台规则" in prompt_all
    assert "抖音平台规则" not in prompt_filtered
    assert "浏览器操作安全" in prompt_filtered
