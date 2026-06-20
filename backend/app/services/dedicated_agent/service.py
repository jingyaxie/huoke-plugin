from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.schemas.agent_profile import AgentProfileCreate
from app.services.agent_profile_store import AgentProfileStore
from app.services.agent_strategy import resolve_agent_strategy
from app.services.dedicated_agent.constants import (
    GENERAL_AGENT_PROFILE_ID,
    is_task_dedicated_profile,
)
from app.services.task_brief_service import TaskBrief
from app.services.task_skill_playbook import build_allowed_skills


class DedicatedAgentService:
    """通用 Chat 与任务专用智能体的边界与经验沙盒。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._profiles = AgentProfileStore(settings)

    @staticmethod
    def resolve_chat_profile_id(requested: str | None) -> str:
        """外层 Chat 固定走通用智能体；禁止误用 task-* 专用档案。"""
        pid = (requested or GENERAL_AGENT_PROFILE_ID).strip() or GENERAL_AGENT_PROFILE_ID
        if is_task_dedicated_profile(pid):
            return GENERAL_AGENT_PROFILE_ID
        return pid

    @staticmethod
    def resolve_strategy_for_brief(brief: TaskBrief):
        platform = (brief.platform or "douyin").strip().lower()
        sid = brief.agent_strategy or (brief.goals or {}).get("agent_strategy")
        return resolve_agent_strategy(str(sid) if sid else None, platform=platform)

    def resolve_job_profile_id(self, brief: TaskBrief) -> str:
        if brief.agent_profile_id:
            return str(brief.agent_profile_id).strip()
        return self.resolve_strategy_for_brief(brief).profile_id

    @staticmethod
    def skill_ids_for_brief(brief: TaskBrief) -> list[str]:
        allowed = brief.allowed_skills if isinstance(brief.allowed_skills, list) else []
        ids: list[str] = []
        for row in allowed:
            if isinstance(row, dict):
                sid = str(row.get("skill_id") or "").strip()
                if sid:
                    ids.append(sid)
        if ids:
            return sorted(set(ids))
        platform = (brief.platform or "douyin").strip().lower()
        strategy = DedicatedAgentService.resolve_strategy_for_brief(brief)
        return sorted(
            {
                str(row.get("skill_id") or "").strip()
                for row in build_allowed_skills(platform, strategy=strategy)
                if row.get("skill_id")
            }
        )

    def ensure_platform_task_profile(self, tenant_id: str, brief: TaskBrief) -> str:
        """确保策略专用智能体档案存在，Skill 白名单与 TaskBrief 对齐。"""
        strategy = self.resolve_strategy_for_brief(brief)
        profile_id = self.resolve_job_profile_id(brief)
        skill_ids = self.skill_ids_for_brief(brief)

        existing = self._profiles.get(tenant_id, profile_id)
        if existing is None:
            template = self._profiles.task_agent_profile_from_strategy(strategy)
            try:
                self._profiles.create(
                    tenant_id,
                    AgentProfileCreate(
                        id=profile_id,
                        name=template.name,
                        description=template.description,
                        system_prompt=template.system_prompt,
                        inherit_base_prompt=template.inherit_base_prompt,
                        inherit_workflow_prompt=template.inherit_workflow_prompt,
                        exclude_rule_ids=list(template.exclude_rule_ids),
                        inherit_experience_prompt=template.inherit_experience_prompt,
                        skill_ids=skill_ids,
                        platforms=[strategy.platform],
                        enabled=True,
                    ),
                )
            except ValueError:
                pass
        else:
            from app.schemas.agent_profile import AgentProfileUpdate

            if sorted(existing.skill_ids or []) != skill_ids:
                try:
                    self._profiles.update(
                        tenant_id,
                        profile_id,
                        AgentProfileUpdate(skill_ids=skill_ids),
                    )
                except KeyError:
                    pass
        return profile_id

    def attach_to_orchestration_plan(
        self,
        tenant_id: str,
        brief: TaskBrief,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        strategy = self.resolve_strategy_for_brief(brief)
        profile_id = self.ensure_platform_task_profile(tenant_id, brief)
        skill_ids = self.skill_ids_for_brief(brief)
        dedicated = {
            "kind": "platform_task",
            "strategy_id": strategy.id,
            "strategy_label": strategy.label,
            "execution_mode": strategy.execution_mode,
            "profile_id": profile_id,
            "platform": brief.platform,
            "skill_ids": skill_ids,
            "experience_root": f"agent_sandboxes/{profile_id}/skills",
        }
        plan["dedicated_agent"] = dedicated
        plan["execution_note"] = (
            f"{plan.get('execution_note') or ''} "
            f"执行策略 `{strategy.label}`（{strategy.id}）；专用智能体 `{profile_id}` "
            f"（Skill 白名单 {len(skill_ids)} 项；与 Chat 通用智能体隔离）。"
        ).strip()
        return dedicated

    def dedicated_meta_from_job_result(self, job_result: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(job_result, dict):
            return {}
        orch = job_result.get("orchestration")
        if isinstance(orch, dict) and isinstance(orch.get("dedicated_agent"), dict):
            return orch["dedicated_agent"]
        if isinstance(job_result.get("dedicated_agent"), dict):
            return job_result["dedicated_agent"]
        return {}

    def profile_id_from_job_result(self, job_result: dict[str, Any] | None, *, platform: str) -> str:
        meta = self.dedicated_meta_from_job_result(job_result)
        pid = str(meta.get("profile_id") or "").strip()
        if pid:
            return pid
        brief_raw = {}
        if isinstance(job_result, dict):
            orch = job_result.get("orchestration")
            if isinstance(orch, dict):
                brief_raw = orch.get("task_brief") or {}
        if isinstance(brief_raw, dict) and brief_raw.get("agent_profile_id"):
            return str(brief_raw["agent_profile_id"]).strip()
        return resolve_agent_strategy(None, platform=platform).profile_id
