from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.services.page_diagnosis.contracts import CrawlFailureSignal, PageDiagnosis
from app.services.page_diagnosis.failure_mapping import TERMINAL_FAILURE_CLASSES
from app.services.page_diagnosis.mappers.registry import infer_implementation, normalize_failure
from app.services.page_diagnosis.providers import PageSnapshotProvider, build_snapshot_provider
from app.services.page_diagnosis.service import PageDiagnosisService
from app.services.page_diagnosis.screenshot_store import capture_page_screenshot
from app.services.skill_failure import classify_skill_failure, is_terminal_failure


def should_diagnose_failure(
    *,
    skill_result: dict[str, Any] | None,
    signal: CrawlFailureSignal,
    state: dict[str, Any],
    action: str,
) -> bool:
    skill_result = skill_result or {}
    if str(skill_result.get("status", "")).lower() not in {"failed", "error"} and not skill_result.get("error"):
        if classify_skill_failure(skill_result) is None:
            return False
    if state.get("crawl_risk_blocked"):
        return True
    if signal.failure_class in TERMINAL_FAILURE_CLASSES:
        return True
    if is_terminal_failure(classify_skill_failure(skill_result)):
        return True
    if action.startswith("crawl") and int(state.get("crawl_failures") or 0) >= 1:
        return True
    return False


def apply_diagnosis_to_state(state: dict[str, Any], diagnosis: PageDiagnosis) -> None:
    payload = diagnosis.model_dump()
    state["page_diagnosis"] = payload
    if diagnosis.user_title:
        state["wake_reason"] = diagnosis.user_title
    if diagnosis.user_steps:
        state["next_action"] = "\n".join(
            f"{idx + 1}. {step}" for idx, step in enumerate(diagnosis.user_steps) if str(step).strip()
        )


def merge_diagnosis_into_suspend_brief(
    brief: dict[str, Any],
    supervisor_state: dict[str, Any],
) -> dict[str, Any]:
    diag = supervisor_state.get("page_diagnosis")
    if not isinstance(diag, dict):
        return brief
    out = dict(brief)
    if diag.get("user_title"):
        out["reason"] = str(diag["user_title"])
    if diag.get("user_summary"):
        out["user_summary"] = str(diag["user_summary"])
    steps = diag.get("user_steps")
    if isinstance(steps, list) and steps:
        out["next_action"] = "\n".join(
            f"{idx + 1}. {step}" for idx, step in enumerate(steps) if str(step).strip()
        )
    if diag.get("issue_type"):
        out["issue_type"] = diag["issue_type"]
    if diag.get("confidence") is not None:
        out["confidence"] = diag["confidence"]
    evidence = diag.get("evidence")
    if isinstance(evidence, list) and evidence:
        out["evidence"] = evidence
    if diag.get("can_auto_retry") is not None:
        out["can_auto_retry"] = diag["can_auto_retry"]
    if diag.get("screenshot_ref"):
        out["screenshot_ref"] = diag["screenshot_ref"]
    if diag.get("source"):
        out["diagnosis_source"] = diag["source"]
    return out


def extract_page_diagnosis(job_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(job_result, dict):
        return None
    diag = job_result.get("page_diagnosis")
    if isinstance(diag, dict):
        return diag
    state = job_result.get("supervisor_state")
    if isinstance(state, dict) and isinstance(state.get("page_diagnosis"), dict):
        return state["page_diagnosis"]
    return None


class CrawlFailureReporter:
    def __init__(self, settings: Settings, tenant_id: str) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self._service = PageDiagnosisService(settings)

    async def report(
        self,
        *,
        platform: str | None,
        operation: str,
        skill_result: dict[str, Any] | None,
        snapshot_provider: PageSnapshotProvider | None,
        exc: Exception | None = None,
        page: Any | None = None,
        job_id: str | None = None,
    ) -> PageDiagnosis | None:
        if not getattr(self.settings, "page_diagnosis_enabled", True):
            return None

        has_page = page is not None
        implementation = infer_implementation(skill_result, has_page=has_page)
        signal = normalize_failure(
            platform=platform,
            operation=operation,
            implementation=implementation,
            skill_result=skill_result,
            exc=exc,
        )
        if has_page:
            signal.page_available = True

        snapshot = None
        screenshot_bytes = None
        if snapshot_provider is not None:
            try:
                snapshot = await snapshot_provider.collect_safe(timeout=3.0)
            except Exception:
                snapshot = None

        if snapshot is None and page is not None and getattr(
            self.settings, "page_diagnosis_screenshot_enabled", True
        ):
            screenshot_bytes = await capture_page_screenshot(page)

        if snapshot and snapshot.screenshot_ref and page is not None and screenshot_bytes is None:
            screenshot_bytes = await capture_page_screenshot(page)

        return await self._service.analyze(
            signal,
            snapshot,
            screenshot_bytes=screenshot_bytes,
        )
