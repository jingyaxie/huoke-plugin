"""浏览器会话与智能体档案 / Skill 绑定（不含页面经验学习）。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def resolve_active_skill_id(profile: Any, explicit_skill_ids: set[str] | list[str] | None) -> str | None:
    explicit = list(explicit_skill_ids or [])
    if explicit:
        return explicit[0]
    skill_ids = list(getattr(profile, "skill_ids", None) or [])
    if skill_ids:
        return skill_ids[0]
    return None


def bind_session_sandbox(
    session: Any,
    *,
    agent_profile_id: str,
    profile_skill_ids: list[str] | None,
    explicit_skill_ids: set[str] | list[str] | None,
) -> None:
    """绑定浏览器会话到智能体档案 + Skill。"""
    explicit = set(explicit_skill_ids or [])
    session.agent_profile_id = agent_profile_id
    session.active_skill_id = resolve_active_skill_id(
        SimpleNamespace(skill_ids=profile_skill_ids or []),
        explicit,
    )
    session.skip_home_warmup = (agent_profile_id or "").startswith("task-")
    session.stable_mode = session.skip_home_warmup
