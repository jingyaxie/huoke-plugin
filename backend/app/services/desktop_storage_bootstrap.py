"""桌面版用户 storage 初始化：确保内置 Skill 等关键数据就绪。"""
from __future__ import annotations

import logging

from app.core.config import Settings
from app.services.skill_store import SkillStore

logger = logging.getLogger(__name__)

CORE_DESKTOP_SKILL_IDS = frozenset(
    {
        "check-login",
        "douyin-keyword-comments",
        "reply-comment",
        "send-dm",
        "follow-user",
    }
)


def bootstrap_desktop_storage(settings: Settings) -> list[str]:
    """桌面模式启动时补齐用户 storage 中的全局 Skill。返回警告信息。"""
    if not settings.desktop_mode:
        return []

    store = SkillStore(settings)
    store._ensure_global_defaults()

    tenant_id = settings.default_tenant_id
    enabled = {skill.id for skill in store.list_enabled(tenant_id)}
    missing = CORE_DESKTOP_SKILL_IDS - enabled
    if not missing:
        return []

    store._merge_missing_global_defaults()
    enabled = {skill.id for skill in store.list_enabled(tenant_id)}
    still_missing = CORE_DESKTOP_SKILL_IDS - enabled
    if still_missing:
        message = (
            "桌面内置 Skill 未完整初始化，缺少: "
            + ", ".join(sorted(still_missing))
            + "。请退出应用并删除 %APPDATA%\\com.huoke.desktop\\runtime-work 后重试。"
        )
        logger.error(message)
        return [message]

    logger.info(
        "desktop storage bootstrap merged skills: %s",
        ", ".join(sorted(missing)),
    )
    return []
