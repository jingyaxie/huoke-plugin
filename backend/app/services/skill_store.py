from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.skill import (
    LEGACY_BUILTIN_HANDLER_ALIASES,
    SkillCreate,
    SkillOut,
    SkillScope,
    SkillUpdate,
    skill_tool_name,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)



def _bundled_skill_bootstrap_paths() -> list[Path]:
    """桌面版 bootstrap 候选路径（runtime-work 可能缺 backend/storage）。"""
    paths: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    backend_root = Path(__file__).resolve().parents[2]
    add(backend_root / "storage" / "skills" / "global.json")

    bundle_dir = os.environ.get("HUOKE_BUNDLE_DIR", "").strip()
    if bundle_dir:
        add(Path(bundle_dir) / "backend" / "storage" / "skills" / "global.json")

    data_dir = os.environ.get("HUOKE_DATA_DIR", "").strip()
    if data_dir:
        add(Path(data_dir) / "bundle-cache" / "current" / "backend" / "storage" / "skills" / "global.json")

    return paths


def _bootstrap_default_skills() -> list[dict]:
    """从 backend/storage/skills/global.json 加载默认 Skill 定义（单一数据源）。"""
    for bootstrap_path in _bundled_skill_bootstrap_paths():
        if not bootstrap_path.exists():
            continue
        payload = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        skills = payload.get("skills")
        if isinstance(skills, list) and skills:
            return skills
    return [
        {
            "id": "check-login",
            "name": "检查登录状态",
            "description": "检查当前平台是否已登录",
            "type": "builtin",
            "enabled": True,
            "scope": "global",
            "parameters": [],
            "content": "",
            "actions": [],
            "builtin_handler": "login_status",
        }
    ]


def _default_global_skills() -> list[dict]:
    """每次 bootstrap/merge 时重新读取，避免桌面 bundle 在 import 后才就位时只剩 check-login。"""
    return _bootstrap_default_skills()

# 已从 global.json 移除的废弃技能；启动时从磁盘清理，list 时过滤，防止 Docker 卷残留旧定义
DEPRECATED_SKILL_IDS = frozenset(
    {
        "douyin-reply-comment",
        "douyin-hot-api",
        "douyin-search-keyword",
        "douyin-comments-api",
        "douyin-human-journey",
        "social-roam",
        "xhs-feed-api",
        "xhs-search-api",
        "xhs-comments-api",
    }
)

# 旧 slash 命令 → 当前 builtin（仅兼容调用，不再注册为独立 skill）
SKILL_ID_ALIASES: dict[str, str] = {
    "douyin-reply-comment": "reply-comment",
    "search-videos": "search-content",
    "crawl-video-comments": "content-comments",
    "douyin-follow-user": "follow-user",
    "douyin-send-dm": "send-dm",
}


def resolve_skill_id(skill_id: str) -> str:
    return SKILL_ID_ALIASES.get(skill_id, skill_id)

class SkillStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.global_path = settings.storage_root / "skills" / "global.json"
        self.global_path.parent.mkdir(parents=True, exist_ok=True)

    def _tenant_path(self, tenant_id: str) -> Path:
        safe = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / safe / "skills.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_global_defaults(self) -> None:
        if not self.global_path.exists():
            now = _utc_now().isoformat()
            payload = {
                "skills": [
                    {**skill, "created_at": now, "updated_at": now}
                    for skill in _default_global_skills()
                ]
            }
            self.global_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return
        self._merge_missing_global_defaults()
        self._prune_deprecated_skills()
        self._repair_legacy_global_handlers()

    def _repair_legacy_global_handlers(self) -> None:
        skills = self._load_raw(self.global_path)
        changed = False
        now = _utc_now().isoformat()
        for raw in skills:
            handler = raw.get("builtin_handler")
            mapped = LEGACY_BUILTIN_HANDLER_ALIASES.get(handler or "")
            if not mapped:
                continue
            raw["builtin_handler"] = mapped
            raw["updated_at"] = now
            changed = True
        if changed:
            self.global_path.write_text(
                json.dumps({"skills": skills}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _prune_deprecated_skills(self) -> None:
        if not self.global_path.exists():
            return
        skills = self._load_raw(self.global_path)
        filtered = [s for s in skills if s.get("id") not in DEPRECATED_SKILL_IDS]
        if len(filtered) == len(skills):
            return
        self.global_path.write_text(
            json.dumps({"skills": filtered}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _merge_missing_global_defaults(self) -> None:
        existing = self._load_raw(self.global_path)
        existing_ids = {s.get("id") for s in existing}
        now = _utc_now().isoformat()
        changed = False
        for skill in _default_global_skills():
            if skill["id"] in existing_ids:
                continue
            existing.append({**skill, "created_at": now, "updated_at": now})
            changed = True
        if changed:
            self.global_path.write_text(
                json.dumps({"skills": existing}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _load_raw(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            skills = raw.get("skills", [])
        elif isinstance(raw, list):
            skills = raw
        else:
            raise ValueError("skills 文件格式无效")
        if not isinstance(skills, list):
            raise ValueError("skills 必须是数组")
        return skills

    def _to_out(self, raw: dict, scope: SkillScope) -> SkillOut:
        data = dict(raw)
        data["scope"] = scope
        data["tool_name"] = skill_tool_name(data["id"])
        return SkillOut.model_validate(data)

    def list_all(self, tenant_id: str, *, include_disabled: bool = True) -> list[SkillOut]:
        self._ensure_global_defaults()
        merged: dict[str, SkillOut] = {}
        for raw in self._load_raw(self.global_path):
            skill = self._to_out(raw, "global")
            merged[skill.id] = skill
        for raw in self._load_raw(self._tenant_path(tenant_id)):
            skill = self._to_out(raw, "tenant")
            merged[skill.id] = skill
        items = list(merged.values())
        if not include_disabled:
            items = [s for s in items if s.enabled]
        items = [s for s in items if s.id not in DEPRECATED_SKILL_IDS]
        return sorted(items, key=lambda s: (s.scope != "global", s.name))

    def list_enabled(self, tenant_id: str) -> list[SkillOut]:
        return self.list_all(tenant_id, include_disabled=False)

    def get(self, tenant_id: str, skill_id: str) -> SkillOut | None:
        resolved = resolve_skill_id(skill_id)
        for skill in self.list_all(tenant_id, include_disabled=True):
            if skill.id == resolved:
                return skill
        return None

    def create(self, tenant_id: str, payload: SkillCreate, *, scope: SkillScope = "tenant") -> SkillOut:
        path = self.global_path if scope == "global" else self._tenant_path(tenant_id)
        if scope == "global":
            self._ensure_global_defaults()
        skills = self._load_raw(path)
        if any(s.get("id") == payload.id for s in skills):
            raise ValueError(f"技能 ID 已存在: {payload.id}")
        now = _utc_now().isoformat()
        record = payload.model_dump()
        record["scope"] = scope
        record["created_at"] = now
        record["updated_at"] = now
        skills.append(record)
        path.write_text(json.dumps({"skills": skills}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(record, scope)

    def update(self, tenant_id: str, skill_id: str, payload: SkillUpdate) -> SkillOut:
        skill = self.get(tenant_id, skill_id)
        if skill is None:
            raise KeyError(skill_id)
        path = self.global_path if skill.scope == "global" else self._tenant_path(tenant_id)
        skills = self._load_raw(path)
        updated: dict | None = None
        for idx, raw in enumerate(skills):
            if raw.get("id") != skill_id:
                continue
            merged = dict(raw)
            for key, value in payload.model_dump(exclude_none=True).items():
                merged[key] = value
            merged["updated_at"] = _utc_now().isoformat()
            skills[idx] = merged
            updated = merged
            break
        if updated is None:
            raise KeyError(skill_id)
        path.write_text(json.dumps({"skills": skills}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(updated, skill.scope)

    def delete(self, tenant_id: str, skill_id: str) -> bool:
        skill = self.get(tenant_id, skill_id)
        if skill is None:
            return False
        if skill.scope == "global":
            raise ValueError("不能删除全局内置技能，可将其 disabled 设为 false")
        path = self._tenant_path(tenant_id)
        skills = self._load_raw(path)
        new_skills = [s for s in skills if s.get("id") != skill_id]
        if len(new_skills) == len(skills):
            return False
        path.write_text(json.dumps({"skills": new_skills}, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def load_safe(self, tenant_id: str) -> list[SkillOut]:
        try:
            return self.list_enabled(tenant_id)
        except (json.JSONDecodeError, ValidationError, ValueError):
            return []

    def list_tenant_raw(self, tenant_id: str) -> list[dict]:
        return self._load_raw(self._tenant_path(tenant_id))

    def export_tenant_skills(self, tenant_id: str, skill_ids: list[str] | None = None) -> list[dict]:
        skills = self.list_tenant_raw(tenant_id)
        if skill_ids:
            wanted = set(skill_ids)
            skills = [s for s in skills if s.get("id") in wanted]
        exportable: list[dict] = []
        for raw in skills:
            item = {k: v for k, v in raw.items() if k not in {"scope", "tool_name"}}
            exportable.append(item)
        return exportable

    def import_skills(
        self,
        tenant_id: str,
        payloads: list[SkillCreate],
        *,
        overwrite: bool = False,
    ) -> tuple[list[str], list[str], list[str]]:
        imported: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        for payload in payloads:
            try:
                existing = self.get(tenant_id, payload.id)
                if existing and existing.scope == "tenant":
                    if overwrite:
                        self.update(tenant_id, payload.id, SkillUpdate(**payload.model_dump()))
                        imported.append(payload.id)
                    else:
                        skipped.append(payload.id)
                elif existing and existing.scope == "global":
                    if overwrite:
                        self.create(tenant_id, payload, scope="tenant")
                        imported.append(payload.id)
                    else:
                        skipped.append(payload.id)
                else:
                    self.create(tenant_id, payload, scope="tenant")
                    imported.append(payload.id)
            except Exception as exc:
                errors.append(f"{payload.id}: {exc}")
        return imported, skipped, errors
