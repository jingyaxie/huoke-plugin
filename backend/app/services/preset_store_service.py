from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.schemas.presets import PresetCreateRequest, PresetKind, PresetListOut, PresetTemplate, PresetUpdateRequest


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PresetStoreService:
    def __init__(self, settings: Settings, tenant_id: str) -> None:
        self.root = settings.storage_root / "tenants" / tenant_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "presets.json"

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.is_file():
            return {"comments": [], "dm-openers": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"comments": [], "dm-openers": []}
        if not isinstance(raw, dict):
            return {"comments": [], "dm-openers": []}
        return {
            "comments": list(raw.get("comments") or []),
            "dm-openers": list(raw.get("dm-openers") or raw.get("dm_openers") or []),
        }

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_presets(self, kind: PresetKind) -> PresetListOut:
        data = self._load()
        items = [PresetTemplate.model_validate(row) for row in data.get(kind, [])]
        items.sort(key=lambda row: row.updated_at or row.created_at or "", reverse=True)
        return PresetListOut(items=items, total=len(items))

    def create_preset(self, kind: PresetKind, payload: PresetCreateRequest) -> PresetTemplate:
        data = self._load()
        now = _utc_now()
        item = PresetTemplate(
            id=str(uuid.uuid4()),
            name=payload.name.strip(),
            content=payload.content.strip(),
            created_at=now,
            updated_at=now,
        )
        data.setdefault(kind, []).append(item.model_dump())
        self._save(data)
        return item

    def update_preset(self, kind: PresetKind, preset_id: str, payload: PresetUpdateRequest) -> PresetTemplate:
        data = self._load()
        rows = data.get(kind, [])
        for idx, row in enumerate(rows):
            if str(row.get("id")) != preset_id:
                continue
            if payload.name is not None:
                row["name"] = payload.name.strip()
            if payload.content is not None:
                row["content"] = payload.content.strip()
            row["updated_at"] = _utc_now()
            rows[idx] = row
            self._save(data)
            return PresetTemplate.model_validate(row)
        raise KeyError("preset_not_found")

    def delete_preset(self, kind: PresetKind, preset_id: str) -> bool:
        data = self._load()
        rows = data.get(kind, [])
        next_rows = [row for row in rows if str(row.get("id")) != preset_id]
        if len(next_rows) == len(rows):
            return False
        data[kind] = next_rows
        self._save(data)
        return True
