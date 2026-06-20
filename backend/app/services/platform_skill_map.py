from __future__ import annotations

PLATFORM_KEYWORD_SKILL: dict[str, str] = {
    "douyin": "douyin-keyword-comments",
    "xiaohongshu": "xhs-keyword-comments",
    "kuaishou": "kuaishou-keyword-comments",
}

SKILL_PLATFORM: dict[str, str] = {
    skill_id: platform for platform, skill_id in PLATFORM_KEYWORD_SKILL.items()
}


def keyword_skill_for_platform(platform: str) -> str:
    skill_id = PLATFORM_KEYWORD_SKILL.get(platform)
    if not skill_id:
        raise ValueError(f"平台 {platform} 未配置关键词评论 Skill")
    return skill_id


def crawl_skill_for_platform(platform: str) -> str:
    """平台默认抓取 Skill（与 AgentStrategy 默认策略一致）。"""
    from app.services.agent_strategy import default_strategy_for_platform

    return default_strategy_for_platform(platform).crawl_skill_id


def platform_for_skill_id(skill_id: str) -> str | None:
    """平台专属 keyword-comments 技能 → 平台 ID；通用技能返回 None。"""
    return SKILL_PLATFORM.get(skill_id)
