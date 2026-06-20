from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DouyinUiFlowExperience:
    """抖音 UI Flow 本地经验：记住成功的 selector / 提交方式，越跑越顺。"""

    def __init__(self, settings: Settings, *, tenant_id: str, account_id: str) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.path = (
            settings.storage_root
            / "tenants"
            / tenant_id
            / "accounts"
            / account_id
            / "ui_flow_douyin.json"
        )
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "runs": 0, "phases": {}, "phase_ms": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("version", 1)
                payload.setdefault("runs", 0)
                payload.setdefault("phases", {})
                payload.setdefault("phase_ms", {})
                return payload
        except Exception:
            pass
        return {"version": 1, "runs": 0, "phases": {}, "phase_ms": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def prefer(self, phase: str, key: str, candidates: tuple[str, ...]) -> tuple[str, ...]:
        saved = (self.data.get("phases") or {}).get(phase, {}).get(key)
        if saved and saved in candidates:
            return (saved, *(c for c in candidates if c != saved))
        return candidates

    def record_phase(self, phase: str, *, elapsed_ms: int, hints: dict[str, Any] | None = None) -> None:
        phases = self.data.setdefault("phases", {})
        bucket = phases.setdefault(phase, {})
        if hints:
            bucket.update({k: v for k, v in hints.items() if v})
        ms_bucket = self.data.setdefault("phase_ms", {})
        prev = int(ms_bucket.get(phase) or 0)
        ms_bucket[phase] = int((prev + elapsed_ms) / 2) if prev else elapsed_ms

    def record_success(self, *, keyword: str, stages: list[str]) -> None:
        self.data["runs"] = int(self.data.get("runs") or 0) + 1
        self.data["last_success_at"] = _utc_now()
        self.data["last_keyword"] = keyword
        self.data["last_stages"] = stages

    def suggested_wait_ms(self, phase: str, default: int) -> int:
        saved = int((self.data.get("phase_ms") or {}).get(phase) or 0)
        if saved <= 0:
            return default
        return min(max(saved, default // 2), default * 2)
