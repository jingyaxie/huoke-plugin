from __future__ import annotations

# 外层 Chat：通用智能体
GENERAL_AGENT_PROFILE_ID = "default"

# 任务编排：按平台绑定的专用智能体（经验沙盒隔离于 Chat）
PLATFORM_TASK_PROFILE_PREFIX = "task-"


def platform_task_profile_id(platform: str) -> str:
    """平台默认任务专用档案（与默认 AgentStrategy.profile_id 对齐）。"""
    from app.services.agent_strategy import default_strategy_for_platform

    plat = (platform or "douyin").strip().lower()
    return default_strategy_for_platform(plat).profile_id


def is_task_dedicated_profile(profile_id: str | None) -> bool:
    pid = (profile_id or "").strip()
    return pid.startswith(PLATFORM_TASK_PROFILE_PREFIX)


def is_general_agent_profile(profile_id: str | None) -> bool:
    pid = (profile_id or GENERAL_AGENT_PROFILE_ID).strip() or GENERAL_AGENT_PROFILE_ID
    return pid == GENERAL_AGENT_PROFILE_ID and not is_task_dedicated_profile(pid)
