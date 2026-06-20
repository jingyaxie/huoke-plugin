from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent_strategy.registry import AgentStrategy

# Supervisor 战术动作 → 唯一 Skill 绑定（task_supervisor_service 通过 skill_id_for_supervisor_action 解析）
SUPERVISOR_SKILL_BINDINGS: list[dict[str, Any]] = [
    {
        "phase": "预检",
        "supervisor_action": "check_login",
        "skill_id": "check-login",
        "purpose": "检查平台登录态，未登录则中止触达",
        "required_params": [],
        "optional_params": [],
    },
    {
        "phase": "抓取",
        "supervisor_action": "crawl_keyword",
        "skill_id": "douyin-keyword-comments",
        "purpose": "类人分步：搜索框输入关键词，监听浏览器请求采集评论入库",
        "required_params": ["keyword"],
        "optional_params": ["content_limit", "video_limit", "days", "region", "show_browser"],
    },
    {
        "phase": "抓取",
        "supervisor_action": "crawl_content_url",
        "skill_id": "content-comments",
        "purpose": "手动获客：抓取单条视频/笔记评论入库",
        "required_params": ["video_url"],
        "optional_params": ["note_url", "days", "show_browser"],
    },
    {
        "phase": "抓取",
        "supervisor_action": "crawl_profile",
        "skill_id": "douyin-profile-comments",
        "purpose": "手动获客：打开主页 URL，监听 aweme/post 接口采集视频并抓取评论",
        "required_params": ["profile_url"],
        "optional_params": ["days", "video_publish_days", "crawl_video_limit", "show_browser"],
    },
    {
        "phase": "评估",
        "supervisor_action": "evaluate_leads",
        "skill_id": "evaluate-leads",
        "purpose": "批量 LLM 评估入库评论是否符合线索标准（Supervisor 内部阶段，非 Skill Store）",
        "required_params": [],
        "optional_params": ["platform"],
    },
    {
        "phase": "观察",
        "supervisor_action": "query_stats",
        "skill_id": "query-interaction-stats",
        "purpose": "查询今日 reply/follow/dm 配额与去重状态",
        "required_params": [],
        "optional_params": ["platform", "period", "reply_limit", "follow_limit", "dm_limit"],
    },
    {
        "phase": "观察",
        "supervisor_action": "query_comments",
        "skill_id": "query-stored-comments",
        "purpose": "从数据库查询已入库评论，供触达前筛选线索",
        "required_params": [],
        "optional_params": ["platform", "content_id", "comment_text_contains", "limit"],
    },
    {
        "phase": "触达",
        "supervisor_action": "reply",
        "skill_id": "reply-comment",
        "purpose": "在视频/笔记下回复目标用户评论",
        "required_params": ["comment_id", "reply_text"],
        "optional_params": ["content_id", "video_url", "note_url", "comment_text"],
    },
    {
        "phase": "触达",
        "supervisor_action": "dm",
        "skill_id": "send-dm",
        "purpose": "向目标用户发送私信",
        "required_params": ["message"],
        "optional_params": ["user_id", "sec_uid", "username"],
    },
    {
        "phase": "触达",
        "supervisor_action": "follow",
        "skill_id": "follow-user",
        "purpose": "关注目标用户主页",
        "required_params": [],
        "optional_params": ["user_id", "sec_uid", "username"],
    },
]

FORBIDDEN_SKILL_IDS = frozenset()

ACTION_TO_SKILL: dict[str, str] = {
    item["supervisor_action"]: item["skill_id"] for item in SUPERVISOR_SKILL_BINDINGS
}


def _resolve_crawl_skill(platform: str, *, strategy: AgentStrategy | None = None) -> str:
    if strategy is not None:
        return strategy.crawl_skill_id
    from app.services.agent_strategy import default_strategy_for_platform

    return default_strategy_for_platform(platform).crawl_skill_id


def skill_id_for_supervisor_action(
    action: str,
    platform: str,
    *,
    strategy_id: str | None = None,
    strategy: AgentStrategy | None = None,
) -> str | None:
    """Supervisor action → Skill ID（抓取动作按策略或平台解析）。"""
    if action == "crawl_keyword":
        if strategy is None and strategy_id:
            from app.services.agent_strategy import resolve_agent_strategy

            strategy = resolve_agent_strategy(strategy_id, platform=platform)
        return _resolve_crawl_skill(platform, strategy=strategy)
    if action == "crawl_profile":
        if platform == "douyin":
            return "douyin-profile-comments"
        if platform == "xiaohongshu":
            return "xhs-profile-comments"
    return ACTION_TO_SKILL.get(action)


def skill_id_from_brief(brief: Any, action: str) -> str | None:
    """优先从 TaskBrief.allowed_skills 解析；回退 strategy/platform 默认。"""
    for row in getattr(brief, "allowed_skills", None) or []:
        if isinstance(row, dict) and row.get("supervisor_action") == action:
            sid = str(row.get("skill_id") or "").strip()
            if sid:
                return sid
    platform = getattr(brief, "platform", None) or "douyin"
    strategy_id = getattr(brief, "agent_strategy", None) or (getattr(brief, "goals", None) or {}).get("agent_strategy")
    return skill_id_for_supervisor_action(action, platform, strategy_id=strategy_id)


def allowed_supervisor_actions() -> list[str]:
    return list(ACTION_TO_SKILL.keys()) + ["suspend", "complete", "fail"]


def build_allowed_skills(platform: str, *, strategy: AgentStrategy | None = None) -> list[dict[str, Any]]:
    """结构化 Skill 白名单，写入 TaskBrief.allowed_skills。"""
    platform = (platform or "douyin").strip().lower()
    items: list[dict[str, Any]] = []
    for row in SUPERVISOR_SKILL_BINDINGS:
        skill_id = row["skill_id"]
        if row["supervisor_action"] == "crawl_keyword":
            skill_id = _resolve_crawl_skill(platform, strategy=strategy)
        elif row["supervisor_action"] == "crawl_profile":
            skill_id = skill_id_for_supervisor_action("crawl_profile", platform, strategy=strategy) or skill_id
        purpose = row["purpose"]
        if row["supervisor_action"] == "crawl_keyword" and strategy is not None and strategy.crawl_purpose:
            purpose = strategy.crawl_purpose
        entry = {
            "phase": row["phase"],
            "supervisor_action": row["supervisor_action"],
            "skill_id": skill_id,
            "purpose": purpose,
            "required_params": list(row["required_params"]),
            "optional_params": list(row["optional_params"]),
        }
        items.append(entry)
    return items


def build_skill_playbook_md(platform: str, *, strategy: AgentStrategy | None = None) -> str:
    """生成简报中「Skill 白名单」Markdown 章节。"""
    platform = (platform or "douyin").strip().lower()
    crawl_skill = _resolve_crawl_skill(platform, strategy=strategy)
    mode_label = strategy.label if strategy else "默认"
    lines = [
        "## Skill 白名单（Supervisor 仅允许以下 Skill）",
        "",
        f"执行策略：**{mode_label}**（抓取 Skill：`{crawl_skill}`）",
        "",
        "Supervisor 每轮只能输出 `supervisor_action`，由系统映射到对应 Skill 执行。**禁止臆造 Skill 名称。**",
        "",
        "| 阶段 | Supervisor 动作 | Skill ID | 用途 | 必填参数 |",
        "|------|-----------------|----------|------|----------|",
    ]
    for row in SUPERVISOR_SKILL_BINDINGS:
        skill_id = row["skill_id"]
        if row["supervisor_action"] == "crawl_keyword":
            skill_id = f"`{crawl_skill}`"
        else:
            skill_id = f"`{skill_id}`"
        req = "、".join(f"`{p}`" for p in row["required_params"]) or "—"
        lines.append(
            f"| {row['phase']} | `{row['supervisor_action']}` | {skill_id} | {row['purpose']} | {req} |"
        )

    forbid_lines = [
        "- 禁止使用未在白名单中的 Skill",
        "- 触达前必须先 `query_stats` 确认 `can_do`",
        "",
    ]
    forbid_lines.insert(0, "- 禁止 LLM 手工搜索/拼接搜索 URL/JS 直调接口（crawl_keyword 由 Skill 在搜索框输入关键词后监听浏览器请求）")

    lines.extend(
        [
            "",
            "### 标准执行顺序",
            "1. `check_login` → `check-login`（可选，浏览器操作前）",
            f"2. `crawl_keyword` → `{crawl_skill}`（首轮必做，需 keyword）",
            "3. `query_stats` → `query-interaction-stats`（触达前查配额）",
            "4. `query_comments` → `query-stored-comments`（筛选待触达线索，可选）",
            "5. `reply` / `dm` / `follow` → 对应触达 Skill（配额内择一）",
            "6. 配额用尽且目标未达成 → `suspend`（挂起到次日，非 Skill）",
            "7. 目标达成 → `complete`",
            "",
            "### 禁止",
            *forbid_lines,
        ]
    )
    return "\n".join(lines)


def attach_skill_playbook_to_brief_md(
    brief_md: str,
    platform: str,
    *,
    strategy: AgentStrategy | None = None,
) -> str:
    """确保 brief_md 含规范 Skill 白名单章节（替换旧章节或追加）。"""
    playbook = build_skill_playbook_md(platform, strategy=strategy)
    text = (brief_md or "").strip()
    marker = "## Skill 白名单"
    if marker in text:
        head = text.split(marker, 1)[0].rstrip()
        return f"{head}\n\n{playbook}".strip()
    if text:
        return f"{text}\n\n{playbook}"
    return playbook


def skill_catalog_for_llm(platform: str, *, strategy: AgentStrategy | None = None) -> list[dict[str, Any]]:
    """供 LLM 编排时注入的 Skill 目录摘要。"""
    return [
        {
            "supervisor_action": item["supervisor_action"],
            "skill_id": item["skill_id"],
            "purpose": item["purpose"],
            "required_params": item["required_params"],
        }
        for item in build_allowed_skills(platform, strategy=strategy)
    ]
