from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.agent_profile import AgentProfileCreate, AgentProfileOut, AgentProfileUpdate, ProfileScope


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentProfileStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _tenant_path(self, tenant_id: str) -> Path:
        safe = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / safe / "agent_profiles.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_raw(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        profiles = raw.get("profiles", raw if isinstance(raw, list) else [])
        if not isinstance(profiles, list):
            raise ValueError("profiles 必须是数组")
        return profiles

    def _to_out(self, raw: dict, scope: ProfileScope = "tenant") -> AgentProfileOut:
        data = {k: v for k, v in raw.items() if k not in {"created_at", "updated_at"}}
        data["scope"] = scope
        return AgentProfileOut.model_validate(data)

    @staticmethod
    def default_profile() -> AgentProfileOut:
        return AgentProfileOut(
            id="default",
            name="默认获客助手",
            description="系统内置浏览器自动化助手，使用标准获客流程与 Skill 能力",
            system_prompt="",
            inherit_base_prompt=True,
            inherit_workflow_prompt=True,
            exclude_rule_ids=[],
            inherit_experience_prompt=True,
            skill_ids=[],
            platforms=[],
            enabled=True,
            scope="global",
        )

    @staticmethod
    def pipeline_recovery_profile() -> AgentProfileOut:
        return AgentProfileOut(
            id="pipeline-recovery",
            name="Pipeline Recovery",
            description="Pipeline builtin 失败后的 Agent 兜底（内部专用，不展示在档案列表）",
            system_prompt=(
                "你是 Pipeline Recovery 兜底智能体。父级 keyword-comments builtin 已失败。\n"
                "在限定 Skill 内：先 check-login；可尝试 show_browser=true 重试 keyword-comments，"
                "或 search-content + content-comments 分步抓取。\n"
                "最终在 task_complete.result 返回结构化 JSON："
                '{"platform":"...","keyword":"...","videos":[],"comments_by_video":[]}'
            ),
            inherit_base_prompt=True,
            inherit_workflow_prompt=True,
            exclude_rule_ids=[],
            inherit_experience_prompt=True,
            skill_ids=[],
            platforms=[],
            enabled=True,
            scope="global",
        )

    @staticmethod
    def task_agent_profile_from_strategy(strategy: Any) -> AgentProfileOut:
        """按 AgentStrategy 生成任务专用智能体模板。"""
        from app.services.task_skill_playbook import build_allowed_skills

        plat = strategy.platform
        skill_ids = sorted(
            {str(r.get("skill_id") or "").strip() for r in build_allowed_skills(plat, strategy=strategy) if r.get("skill_id")}
        )
        labels = {"douyin": "抖音", "xiaohongshu": "小红书", "kuaishou": "快手"}
        label = labels.get(plat, plat)
        return AgentProfileOut(
            id=strategy.profile_id,
            name=f"{label}任务专用（{strategy.label}）",
            description=(
                f"任务编排 Supervisor 专用：策略 `{strategy.id}`；"
                f"抓取 `{strategy.crawl_skill_id}`；经验沙盒 {strategy.profile_id}"
            ),
            system_prompt=strategy.system_prompt,
            inherit_base_prompt=strategy.inherit_base_prompt,
            inherit_workflow_prompt=strategy.inherit_workflow_prompt,
            exclude_rule_ids=list(strategy.exclude_rule_ids),
            inherit_experience_prompt=strategy.inherit_experience_prompt,
            skill_ids=skill_ids,
            platforms=[plat],
            enabled=True,
            scope="global",
        )

    @staticmethod
    def platform_task_agent_profile(platform: str) -> AgentProfileOut:
        """按平台默认策略生成任务专用智能体模板。"""
        from app.services.agent_strategy import default_strategy_for_platform

        return AgentProfileStore.task_agent_profile_from_strategy(default_strategy_for_platform(platform))

    def get(self, tenant_id: str, profile_id: str) -> AgentProfileOut | None:
        if profile_id == "default":
            return self.default_profile()
        if profile_id == "pipeline-recovery":
            return self.pipeline_recovery_profile()
        for raw in self._load_raw(self._tenant_path(tenant_id)):
            if raw.get("id") == profile_id:
                return self._to_out(raw, "tenant")
        from app.services.agent_strategy import strategy_by_profile_id

        strategy = strategy_by_profile_id(profile_id)
        if strategy is not None:
            return self.task_agent_profile_from_strategy(strategy)
        return None

    def list_all(self, tenant_id: str, platform: str | None = None) -> list[AgentProfileOut]:
        merged: dict[str, AgentProfileOut] = {"default": self.default_profile()}
        for raw in self._load_raw(self._tenant_path(tenant_id)):
            profile = self._to_out(raw, "tenant")
            merged[profile.id] = profile
        items = [p for p in merged.values() if p.enabled or p.id == "default"]
        if platform:
            items = [p for p in items if not p.platforms or platform in p.platforms]
        return sorted(items, key=lambda p: (p.id != "default", p.name))

    def resolve(self, tenant_id: str, profile_id: str | None) -> AgentProfileOut:
        pid = (profile_id or "default").strip() or "default"
        profile = self.get(tenant_id, pid)
        if profile is None:
            raise ValueError(f"Agent 档案不存在: {pid}")
        if not profile.enabled:
            raise ValueError(f"Agent 档案已禁用: {pid}")
        return profile

    def create(self, tenant_id: str, payload: AgentProfileCreate) -> AgentProfileOut:
        path = self._tenant_path(tenant_id)
        profiles = self._load_raw(path)
        if any(p.get("id") == payload.id for p in profiles):
            raise ValueError(f"Agent 档案 ID 已存在: {payload.id}")
        now = _utc_now().isoformat()
        record = payload.model_dump()
        record["created_at"] = now
        record["updated_at"] = now
        profiles.append(record)
        path.write_text(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(record, "tenant")

    def update(self, tenant_id: str, profile_id: str, payload: AgentProfileUpdate) -> AgentProfileOut:
        if profile_id == "default":
            raise ValueError("不能修改内置默认 Agent")
        path = self._tenant_path(tenant_id)
        profiles = self._load_raw(path)
        updated: dict | None = None
        for idx, raw in enumerate(profiles):
            if raw.get("id") != profile_id:
                continue
            merged = dict(raw)
            for key, value in payload.model_dump(exclude_none=True).items():
                merged[key] = value
            merged["updated_at"] = _utc_now().isoformat()
            profiles[idx] = merged
            updated = merged
            break
        if updated is None:
            raise KeyError(profile_id)
        path.write_text(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(updated, "tenant")

    def delete(self, tenant_id: str, profile_id: str) -> bool:
        if profile_id == "default":
            return False
        path = self._tenant_path(tenant_id)
        profiles = self._load_raw(path)
        new_profiles = [p for p in profiles if p.get("id") != profile_id]
        if len(new_profiles) == len(profiles):
            return False
        path.write_text(json.dumps({"profiles": new_profiles}, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
