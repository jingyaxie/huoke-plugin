from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id

RunStatus = Literal["active", "interrupted", "completed", "failed", "waiting_plan", "waiting_approval"]


class PendingApproval(BaseModel):
    tool_call_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    step: int = 0


class PendingPlan(BaseModel):
    summary: str
    steps: list[dict[str, Any]] = Field(default_factory=list)


class LoopState(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    step: int = 0
    provider: str = "deepseek"
    agent_profile_id: str = "default"
    explicit_skill_ids: list[str] = Field(default_factory=list)
    mode: str = "agent"
    run_mode: str = "auto"
    deferred_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    phase: str = "plan"
    task_snapshot: dict[str, Any] = Field(default_factory=dict)


class AgentRunRecord(BaseModel):
    run_id: str
    browser_session_id: str
    tenant_id: str
    platform: str
    provider: str = "deepseek"
    status: RunStatus = "active"
    mode: str = "agent"
    run_mode: str = "auto"
    agent_profile_id: str = "default"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    pending_plan: PendingPlan | None = None
    pending_approval: PendingApproval | None = None
    loop_state: LoopState | None = None
    review_report: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    execution_plan: dict[str, Any] | None = None
    ui_flow_bootstrap: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_SKILL_SLASH_RE = re.compile(r"(?:^|\s)/([a-z][a-z0-9_-]{1,63})(?:\s|$)")


def parse_explicit_skill_ids(message: str) -> list[str]:
    return list(dict.fromkeys(_SKILL_SLASH_RE.findall(message)))


class AgentRunStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root / "tenants"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, tenant_id: str, run_id: str) -> Path:
        safe_tenant = normalize_tenant_id(tenant_id)
        directory = self.root / safe_tenant / "agent_runs"
        directory.mkdir(parents=True, exist_ok=True)
        safe_run = run_id.replace("/", "_")
        return directory / f"{safe_run}.json"

    def get(self, tenant_id: str, run_id: str) -> AgentRunRecord | None:
        path = self._path_for(tenant_id, run_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AgentRunRecord.model_validate(raw)

    def save(self, record: AgentRunRecord) -> None:
        record.updated_at = _utc_now()
        if record.created_at is None:
            record.created_at = record.updated_at
        path = self._path_for(record.tenant_id, record.run_id)
        path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create(
        self,
        *,
        run_id: str,
        browser_session_id: str,
        tenant_id: str,
        platform: str,
        provider: str,
    ) -> AgentRunRecord:
        record = AgentRunRecord(
            run_id=run_id,
            browser_session_id=browser_session_id,
            tenant_id=tenant_id,
            platform=platform,
            provider=provider,
            status="active",
            messages=[],
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        self.save(record)
        return record

    def delete(self, tenant_id: str, run_id: str) -> bool:
        path = self._path_for(tenant_id, run_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list_for_tenant(self, tenant_id: str, *, limit: int = 50) -> list[AgentRunRecord]:
        safe = normalize_tenant_id(tenant_id)
        directory = self.root / safe / "agent_runs"
        if not directory.exists():
            return []
        records: list[AgentRunRecord] = []
        for path in directory.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                records.append(AgentRunRecord.model_validate(raw))
            except Exception:
                continue
        records.sort(
            key=lambda r: r.updated_at or r.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return records[: max(1, limit)]


def run_title_from_messages(messages: list[dict[str, Any]], *, max_len: int = 48) -> str:
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        text = content.strip().replace("\n", " ")
        if text:
            return text[:max_len] + ("…" if len(text) > max_len else "")
    return "新对话"


def sanitize_message_for_storage(message: dict[str, Any]) -> dict[str, Any]:
    """Remove bulky vision payloads before persisting run history."""
    cleaned = dict(message)
    content = cleaned.get("content")
    if isinstance(content, list):
        new_parts: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                new_parts.append(part)
                continue
            if part.get("type") == "image_url":
                new_parts.append(
                    {
                        "type": "text",
                        "text": "[screenshot attached during run; omitted from storage]",
                    }
                )
            else:
                new_parts.append(part)
        cleaned["content"] = new_parts
    elif isinstance(content, str) and len(content) > 12000:
        try:
            from app.services.agent_network_capture import compact_api_data_for_agent

            parsed = json.loads(content)
            if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                compact_items = []
                for item in parsed["items"]:
                    if not isinstance(item, dict):
                        compact_items.append(item)
                        continue
                    row = dict(item)
                    if "data" in row:
                        row["data"] = compact_api_data_for_agent(
                            row.get("data"),
                            path=str(row.get("path") or ""),
                        )
                    compact_items.append(row)
                parsed = {**parsed, "items": compact_items}
            compact_text = json.dumps(parsed, ensure_ascii=False)
            cleaned["content"] = compact_text if len(compact_text) <= 12000 else compact_text[:12000] + "\n...[truncated]"
        except Exception:
            cleaned["content"] = content[:12000] + "\n...[truncated]"
    return cleaned


def trim_history(messages: list[dict[str, Any]], max_messages: int) -> list[dict[str, Any]]:
    if max_messages <= 0 or len(messages) <= max_messages:
        return messages
    return messages[-max_messages:]
