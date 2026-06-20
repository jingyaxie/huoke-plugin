from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.lead_evaluation_service import (
    DEFAULT_THRESHOLDS,
    accept_evaluation_result,
    build_rule_based_spec,
    compute_spec_hash,
    evaluation_draft_from_payload,
    evaluation_preview_text,
    is_precise_lead,
    precise_threshold_from_spec,
)
from app.services.task_brief_service import TaskBrief


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "storage")


def test_build_rule_based_spec_has_hash():
    brief = TaskBrief(keyword="淋浴房", region="辽宁", title="测试")
    spec = build_rule_based_spec(brief)
    assert spec["schema"] == "huoke.lead_evaluation.v1"
    assert spec["spec_hash"].startswith("sha256:")
    assert compute_spec_hash(spec) == spec["spec_hash"]


def test_build_rule_based_spec_uses_llm_intent_mode():
    brief = TaskBrief(keyword="淋浴房", region="北京", title="测试")
    spec = build_rule_based_spec(brief)
    assert spec["evaluation_mode"] == "llm_intent"
    assert spec["criteria"]["accept_description"] == ""
    assert spec["criteria"]["positive_examples"] == []
    assert spec["business_context"]["keyword"] == "淋浴房"
    preview = evaluation_preview_text(spec)
    assert "使用心得" in preview
    assert "淋浴房" in preview


def test_evaluation_draft_from_payload():
    draft = evaluation_draft_from_payload(
        {"target_customer": "装修业主", "precise_threshold": 0.8}
    )
    assert draft["target_customer"] == "装修业主"
    assert draft["precise_threshold"] == 0.8


def test_build_rule_based_spec_default_precise_threshold():
    spec = build_rule_based_spec(TaskBrief(keyword="淋浴房"))
    assert spec["thresholds"]["precise"] == DEFAULT_THRESHOLDS["precise"]


def test_precise_threshold_migrates_legacy_compiled_default():
    legacy = {"thresholds": {"precise": 0.72, "outreach": 0.55}}
    custom = {"thresholds": {"precise": 0.85, "outreach": 0.55}}
    assert precise_threshold_from_spec(legacy) == DEFAULT_THRESHOLDS["precise"]
    assert precise_threshold_from_spec(custom) == 0.85


def test_accept_evaluation_result_threshold():
    spec = build_rule_based_spec(TaskBrief(keyword="团餐"))
    ok_result = {"is_lead": True, "score": 0.76, "worth_outreach": True}
    borderline = {"is_lead": True, "score": 0.62, "worth_outreach": True}
    bad_result = {"is_lead": True, "score": 0.4, "worth_outreach": True}
    assert accept_evaluation_result(ok_result, spec) is True
    assert accept_evaluation_result(borderline, spec) is True
    assert accept_evaluation_result(bad_result, spec) is False
    assert is_precise_lead(ok_result, spec) is True
    assert is_precise_lead(borderline, spec) is True
    assert is_precise_lead(bad_result, spec) is False


@pytest.mark.asyncio
async def test_compile_without_llm_fallback(settings):
    from app.services.lead_evaluation_service import compile_lead_evaluation_spec

    brief = TaskBrief(keyword="淋浴房", region="沈阳")
    spec = await compile_lead_evaluation_spec(brief, settings=settings, provider="openai")
    assert spec["evaluation_mode"] == "llm_intent"
    assert spec["business_context"]["keyword"] == "淋浴房"
