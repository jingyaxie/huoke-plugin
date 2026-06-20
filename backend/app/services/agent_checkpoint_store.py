from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id


class CheckpointRecord(BaseModel):
    checkpoint_id: str
    run_id: str
    step: int
    tool: str
    url: str | None = None
    title: str | None = None
    created_at: datetime | None = None


class AgentCheckpointStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root / "tenants"

    def _dir_for(self, tenant_id: str, run_id: str) -> Path:
        safe_tenant = normalize_tenant_id(tenant_id)
        safe_run = run_id.replace("/", "_")
        path = self.root / safe_tenant / "agent_runs" / safe_run / "checkpoints"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(
        self,
        tenant_id: str,
        run_id: str,
        *,
        step: int,
        tool: str,
        url: str | None,
        title: str | None,
        storage_state: dict[str, Any],
    ) -> CheckpointRecord:
        checkpoint_id = str(uuid.uuid4())
        directory = self._dir_for(tenant_id, run_id)
        payload = {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "step": step,
            "tool": tool,
            "url": url,
            "title": title,
            "storage_state": storage_state,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = directory / f"{checkpoint_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return CheckpointRecord(
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            step=step,
            tool=tool,
            url=url,
            title=title,
            created_at=datetime.fromisoformat(payload["created_at"]),
        )

    def list_for_run(self, tenant_id: str, run_id: str) -> list[CheckpointRecord]:
        directory = self._dir_for(tenant_id, run_id)
        items: list[CheckpointRecord] = []
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime):
            raw = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                CheckpointRecord(
                    checkpoint_id=raw["checkpoint_id"],
                    run_id=raw["run_id"],
                    step=raw.get("step", 0),
                    tool=raw.get("tool", ""),
                    url=raw.get("url"),
                    title=raw.get("title"),
                    created_at=datetime.fromisoformat(raw["created_at"])
                    if raw.get("created_at")
                    else None,
                )
            )
        return items

    def load(self, tenant_id: str, run_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        path = self._dir_for(tenant_id, run_id) / f"{checkpoint_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def trim(self, tenant_id: str, run_id: str, max_count: int) -> None:
        directory = self._dir_for(tenant_id, run_id)
        files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if len(files) <= max_count:
            return
        for path in files[: len(files) - max_count]:
            path.unlink()
