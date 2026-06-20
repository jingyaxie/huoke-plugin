"""页面失败诊断：跨平台契约与规则引擎测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.page_diagnosis.contracts import CrawlFailureSignal, PageSnapshot
from app.services.page_diagnosis.mappers.registry import normalize_failure, normalize_platform
from app.services.page_diagnosis.reporter import merge_diagnosis_into_suspend_brief, should_diagnose_failure
from app.services.page_diagnosis.rules import fallback_diagnosis, rule_prefilter
from app.services.page_diagnosis.service import PageDiagnosisService
from app.services.page_diagnosis.screenshot_store import resolve_screenshot_path, save_diagnosis_screenshot


def test_normalize_platform_defaults_unknown():
    assert normalize_platform("unknown-platform") == "douyin"


def test_douyin_skill_result_maps_captcha():
    signal = normalize_failure(
        platform="douyin",
        operation="crawl_keyword",
        implementation="playwright",
        skill_result={"status": "failed", "error": "验证码中间页，请手动处理"},
    )
    assert signal.failure_class == "captcha"
    assert signal.platform == "douyin"


def test_xhs_guest_maps_login_required():
    signal = normalize_failure(
        platform="xiaohongshu",
        operation="crawl_keyword",
        implementation="playwright",
        skill_result={"status": "failed", "diagnostic": "当前为游客态，请重新扫码登录"},
    )
    assert signal.failure_class == "auth_required"
    assert signal.guard_hints.get("guest_mode") is True


def test_kuaishou_risk_maps_risk_limit():
    signal = normalize_failure(
        platform="kuaishou",
        operation="crawl_keyword",
        implementation="playwright",
        skill_result={"status": "failed", "error": "操作过于频繁 429"},
    )
    assert signal.failure_class == "risk_limit"


def test_failure_signal_passthrough():
    signal = normalize_failure(
        platform="douyin",
        operation="crawl_profile",
        implementation="custom_v2",
        skill_result={
            "status": "failed",
            "failure_signal": {
                "platform": "douyin",
                "operation": "crawl_profile",
                "implementation": "custom_v2",
                "failure_class": "automation_blocked",
                "message": "blocked",
                "recoverable": False,
            },
        },
    )
    assert signal.implementation == "custom_v2"
    assert signal.failure_class == "automation_blocked"


def test_rule_prefilter_captcha_from_guard_probe():
    signal = CrawlFailureSignal(
        platform="douyin",
        operation="crawl_keyword",
        implementation="playwright",
        failure_class="captcha",
        message="verify",
        guard_hints={"captcha": True},
    )
    snapshot = PageSnapshot(platform="douyin", guard_probe={"captcha": True}, title="验证码中间页")
    diag = rule_prefilter(signal, snapshot)
    assert diag is not None
    assert diag.issue_type == "captcha_required"
    assert diag.confidence >= 0.9
    assert len(diag.user_steps) >= 2


@pytest.fixture
def diag_settings(tmp_path):
    return Settings(
        storage_root=tmp_path / "storage",
        deepseek_api_key="test-key",
        page_diagnosis_llm_enabled=False,
    )


@pytest.mark.asyncio
async def test_service_fallback_when_no_rule_match(diag_settings):
    signal = CrawlFailureSignal(
        platform="douyin",
        operation="crawl_keyword",
        implementation="unknown",
        failure_class="unknown",
        message="something odd",
    )
    diag = await PageDiagnosisService(diag_settings).analyze(signal, None)
    assert diag.source == "fallback"
    assert diag.issue_type == "unknown"
    assert diag.user_steps


@pytest.mark.asyncio
async def test_service_uses_rule_without_llm(diag_settings):
    signal = CrawlFailureSignal(
        platform="douyin",
        operation="crawl_keyword",
        implementation="playwright",
        failure_class="captcha",
        message="verify",
        guard_hints={"captcha": True},
    )
    snapshot = PageSnapshot(platform="douyin", guard_probe={"captcha": True})
    diag = await PageDiagnosisService(diag_settings).analyze(signal, snapshot)
    assert diag.source == "rule"
    assert diag.issue_type == "captcha_required"


def test_screenshot_store_and_resolve(diag_settings):
    png = b"\x89PNG\r\n\x1a\n"
    ref = save_diagnosis_screenshot(
        diag_settings,
        tenant_id="default",
        job_id="job-1",
        png_bytes=png,
    )
    assert ref and "diagnosis/job-1" in ref
    path = resolve_screenshot_path(diag_settings, ref)
    assert path is not None and path.is_file()
    assert resolve_screenshot_path(diag_settings, "../etc/passwd") is None


@pytest.mark.asyncio
async def test_llm_enriches_low_confidence_rule(diag_settings, monkeypatch):
    diag_settings.page_diagnosis_llm_enabled = True
    diag_settings.page_diagnosis_rule_confidence_skip_llm = 0.99

    async def fake_analyze(self, signal, snapshot, *, screenshot_bytes=None, rule_guess=None):
        from app.services.page_diagnosis.contracts import PageDiagnosis

        return PageDiagnosis(
            issue_type="captcha_required",
            confidence=0.91,
            user_title="LLM：需要验证码",
            user_summary="LLM 判断",
            user_steps=["步骤1", "步骤2"],
            platform=signal.platform,
            failure_class=signal.failure_class,
            source="llm",
        )

    monkeypatch.setattr(
        "app.services.page_diagnosis.llm_analyzer.PageDiagnosisLlmAnalyzer.analyze",
        fake_analyze,
    )

    signal = CrawlFailureSignal(
        platform="douyin",
        operation="crawl_keyword",
        implementation="playwright",
        failure_class="captcha",
        message="verify",
        guard_hints={"captcha": True},
    )
    snapshot = PageSnapshot(platform="douyin", guard_probe={"captcha": True})
    diag = await PageDiagnosisService(diag_settings).analyze(signal, snapshot)
    assert diag.source == "llm"
    assert "验证码" in diag.user_title


def test_merge_diagnosis_into_suspend_brief():
    brief = merge_diagnosis_into_suspend_brief(
        {"reason": "旧原因", "next_action": "旧步骤"},
        {
            "page_diagnosis": {
                "user_title": "需要完成抖音人机验证",
                "user_summary": "说明",
                "user_steps": ["步骤A", "步骤B"],
                "issue_type": "captcha_required",
                "confidence": 0.94,
                "evidence": ["检测到验证码"],
            }
        },
    )
    assert brief["reason"] == "需要完成抖音人机验证"
    assert "步骤A" in brief["next_action"]
    assert brief["issue_type"] == "captcha_required"


@pytest.mark.parametrize(
    "platform,message,expected_class",
    [
        ("douyin", "需要登录 cookie", "auth_required"),
        ("xiaohongshu", "游客态", "auth_required"),
        ("kuaishou", "验证码", "captcha"),
    ],
)
def test_cross_platform_mapper_stable(platform, message, expected_class):
    signal = normalize_failure(
        platform=platform,
        operation="crawl_keyword",
        implementation="sidecar",
        skill_result={"status": "failed", "error": message},
    )
    diag = fallback_diagnosis(signal, None)
    assert signal.failure_class == expected_class
    assert diag.platform == platform
    assert len(diag.user_steps) >= 2


def test_should_diagnose_terminal_failure():
    signal = normalize_failure(
        platform="douyin",
        operation="crawl_keyword",
        implementation="playwright",
        skill_result={"status": "failed", "error": "需要登录"},
    )
    assert should_diagnose_failure(
        skill_result={"status": "failed", "error": "需要登录"},
        signal=signal,
        state={},
        action="crawl_keyword",
    )


def test_should_not_diagnose_success():
    signal = normalize_failure(
        platform="douyin",
        operation="crawl_keyword",
        implementation="playwright",
        skill_result={"status": "completed"},
    )
    assert not should_diagnose_failure(
        skill_result={"status": "completed"},
        signal=signal,
        state={},
        action="crawl_keyword",
    )
