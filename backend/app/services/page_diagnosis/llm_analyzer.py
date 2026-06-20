from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.core.config import Settings
from app.services.ai_client import AIClientFactory
from app.services.page_diagnosis.contracts import (
    CrawlFailureSignal,
    IssueType,
    PageDiagnosis,
    PageSnapshot,
)
from app.services.page_diagnosis.failure_mapping import issue_type_for
from app.services.page_diagnosis.guidance import resolve_guidance
from app.services.page_diagnosis.prompts import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_user_payload
from app.services.page_diagnosis.screenshot_store import screenshot_to_data_url

logger = logging.getLogger(__name__)

_VALID_ISSUES: frozenset[str] = frozenset(
    {
        "login_required",
        "login_expired",
        "captcha_required",
        "risk_control",
        "automation_blocked",
        "page_changed",
        "empty_data",
        "network_error",
        "internal_error",
        "unknown",
    }
)


class PageDiagnosisLlmAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._factory = AIClientFactory(settings)

    def _vision_client_and_model(self) -> tuple[Any | None, str | None]:
        if not getattr(self.settings, "agent_vision_enabled", True):
            return None, None
        model = str(getattr(self.settings, "agent_vision_model", None) or "").strip()
        if not model:
            model = str(getattr(self.settings, "openai_model", "") or "").strip()
        if not model or not self.settings.openai_api_key:
            return None, None
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
        )
        return client, model

    async def analyze(
        self,
        signal: CrawlFailureSignal,
        snapshot: PageSnapshot | None,
        *,
        screenshot_bytes: bytes | None = None,
        rule_guess: PageDiagnosis | None = None,
    ) -> PageDiagnosis | None:
        if not getattr(self.settings, "page_diagnosis_llm_enabled", True):
            return None
        if not self._factory.llm_configured() and not self._vision_client_and_model()[0]:
            return None

        timeout = float(getattr(self.settings, "page_diagnosis_llm_timeout_seconds", 8) or 8)
        try:
            return await asyncio.wait_for(
                self._analyze_inner(signal, snapshot, screenshot_bytes, rule_guess),
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug("page diagnosis llm failed: %s", exc)
            return None

    async def _analyze_inner(
        self,
        signal: CrawlFailureSignal,
        snapshot: PageSnapshot | None,
        screenshot_bytes: bytes | None,
        rule_guess: PageDiagnosis | None,
    ) -> PageDiagnosis | None:
        signal_payload = signal.model_dump()
        snapshot_payload = snapshot.model_dump() if snapshot else None
        rule_payload = rule_guess.model_dump() if rule_guess else None
        user_text = build_diagnosis_user_payload(
            signal=signal_payload,
            snapshot=snapshot_payload,
            rule_guess=rule_payload,
        )

        vision_client, vision_model = self._vision_client_and_model()
        use_vision = bool(screenshot_bytes and vision_client and vision_model)

        if use_vision:
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": screenshot_to_data_url(screenshot_bytes or b""),
                                "detail": "low",
                            },
                        },
                    ],
                },
            ]
            client = vision_client
            model = vision_model
        else:
            client = self._factory.llm_client()
            model = self._factory.llm_model()
            if client is None:
                return None
            messages = [
                {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ]

        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return self._coerce_diagnosis(data, signal, snapshot, source="llm")

    def _coerce_diagnosis(
        self,
        data: dict[str, Any],
        signal: CrawlFailureSignal,
        snapshot: PageSnapshot | None,
        *,
        source: str,
    ) -> PageDiagnosis | None:
        issue_raw = str(data.get("issue_type") or "").strip()
        issue_type: IssueType = issue_type_for(signal.failure_class)
        if issue_raw in _VALID_ISSUES:
            issue_type = issue_raw  # type: ignore[assignment]

        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        guidance = resolve_guidance(signal.platform, issue_type)
        user_title = str(data.get("user_title") or guidance.user_title).strip()
        user_summary = str(data.get("user_summary") or guidance.user_summary).strip()
        steps_raw = data.get("user_steps")
        if isinstance(steps_raw, list) and steps_raw:
            user_steps = [str(s).strip() for s in steps_raw if str(s).strip()]
        else:
            user_steps = list(guidance.user_steps)

        evidence_raw = data.get("evidence")
        evidence = [str(x).strip() for x in evidence_raw if str(x).strip()] if isinstance(evidence_raw, list) else []
        if not evidence and signal.message:
            evidence = [signal.message[:120]]

        can_auto_retry = data.get("can_auto_retry")
        if not isinstance(can_auto_retry, bool):
            can_auto_retry = guidance.can_auto_retry

        return PageDiagnosis(
            issue_type=issue_type,
            confidence=confidence,
            user_title=user_title,
            user_summary=user_summary,
            user_steps=user_steps,
            can_auto_retry=can_auto_retry,
            retry_after_seconds=guidance.retry_after_seconds,
            evidence=evidence,
            technical_detail=signal.message or None,
            source=source,  # type: ignore[arg-type]
            platform=signal.platform,
            failure_class=signal.failure_class,
            screenshot_ref=snapshot.screenshot_ref if snapshot else None,
        )
