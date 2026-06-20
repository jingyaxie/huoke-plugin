from __future__ import annotations

from app.core.config import Settings
from app.services.page_diagnosis.contracts import CrawlFailureSignal, PageDiagnosis, PageSnapshot
from app.services.page_diagnosis.llm_analyzer import PageDiagnosisLlmAnalyzer
from app.services.page_diagnosis.rules import fallback_diagnosis, rule_prefilter


class PageDiagnosisService:
    """诊断引擎：规则预筛 → LLM 精判 → fallback。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._llm = PageDiagnosisLlmAnalyzer(settings)

    async def analyze(
        self,
        signal: CrawlFailureSignal,
        snapshot: PageSnapshot | None,
        *,
        screenshot_bytes: bytes | None = None,
    ) -> PageDiagnosis:
        skip_llm_threshold = float(
            getattr(self.settings, "page_diagnosis_rule_confidence_skip_llm", 0.92) or 0.92
        )
        ruled = rule_prefilter(signal, snapshot)
        if ruled is not None and ruled.confidence >= skip_llm_threshold:
            return ruled

        llm_result = await self._llm.analyze(
            signal,
            snapshot,
            screenshot_bytes=screenshot_bytes,
            rule_guess=ruled,
        )
        if llm_result is not None and llm_result.confidence >= 0.6:
            return llm_result
        if ruled is not None:
            return ruled
        return fallback_diagnosis(signal, snapshot)
