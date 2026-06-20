from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ExecutionMode = Literal["skill_flow"]

# 内置策略（Phase 1）；后续可扩展 tenants/{id}/strategies.json
_BUILTIN: dict[str, AgentStrategy] = {}


@dataclass(frozen=True)
class AgentStrategy:
    """任务抓取/执行策略：平台 + 档案 + playbook + 守卫开关。"""

    id: str
    platform: str
    label: str
    description: str
    profile_id: str
    execution_mode: ExecutionMode
    crawl_skill_id: str
    inherit_base_prompt: bool = True
    inherit_workflow_prompt: bool = False
    inherit_experience_prompt: bool = False
    exclude_rule_ids: list[str] = field(default_factory=list)
    system_prompt: str = ""
    ui_flow_runtime: bool = False
    bootstrap_crawl: bool = False
    inline_ui_outreach: bool = False
    ui_first: bool = False
    supervisor_plan_only: bool = False
    crawl_purpose: str = ""


def _register(strategy: AgentStrategy) -> AgentStrategy:
    _BUILTIN[strategy.id] = strategy
    return strategy


SKILL_FLOW_DOUYIN = _register(
    AgentStrategy(
        id="skill-flow-douyin",
        platform="douyin",
        label="类人分步（Skill）",
        description="Skill 独立分步执行：搜索框输入关键词，监听浏览器正常请求入库，再按规则触达",
        profile_id="task-douyin-skill-flow",
        execution_mode="skill_flow",
        crawl_skill_id="douyin-keyword-comments",
        inherit_base_prompt=True,
        inherit_workflow_prompt=True,
        inherit_experience_prompt=False,
        exclude_rule_ids=[],
        system_prompt=(
            "你是抖音获客 **任务专用** 智能体（类人分步 Skill 策略）。\n"
            "纪律：\n"
            "1. 抓取由 Supervisor 调用 douyin-keyword-comments（builtin）；UI 搜索 + 侧栏被动拦截 comment/list\n"
            "2. 触达优先 social-roam 人类模拟：侧栏 UI 回复、点头像进主页关注/私信\n"
            "3. 触达前 query_stats 查配额\n"
            "4. ui_first 模式下禁止 JS 直调 comment/publish、commit/follow 等接口\n"
            "5. 禁止 browser_goto 搜索页、禁止拼接搜索 URL"
        ),
        ui_flow_runtime=False,
        bootstrap_crawl=False,
        inline_ui_outreach=False,
        ui_first=True,
        supervisor_plan_only=True,
        crawl_purpose="类人 UI：搜索框输入关键词，侧栏被动拦截 comment/list，暖场 UI 触达",
    )
)

STANDALONE_BROWSE_DOUYIN = _register(
    AgentStrategy(
        id="standalone-browse-douyin",
        platform="douyin",
        label="一体化浏览（Standalone）",
        description="固定 UI 流程：搜索/主页/单视频 → 点进详情 → 侧栏规则评估 → 同页触达（与 Skill 分步链路并行，可切换）",
        profile_id="task-douyin-standalone-browse",
        execution_mode="skill_flow",
        crawl_skill_id="standalone-keyword-browse",
        inherit_base_prompt=True,
        inherit_workflow_prompt=False,
        inherit_experience_prompt=False,
        exclude_rule_ids=[],
        system_prompt=(
            "你是抖音获客 **任务专用** 智能体（Standalone 一体化浏览策略）。\n"
            "纪律：\n"
            "1. 抓取由 Supervisor 调用 standalone 浏览模块（非 douyin-keyword-comments）\n"
            "2. 在同页 Feed 侧栏完成规则评估与 reply/dm/follow 触达\n"
            "3. 禁止回退到「先入库再查库再重开页触达」的旧分步 Skill 链路"
        ),
        ui_flow_runtime=False,
        bootstrap_crawl=False,
        inline_ui_outreach=True,
        ui_first=True,
        supervisor_plan_only=True,
        crawl_purpose="一体化 UI：搜索/主页点击视频 → 侧栏评估 → 同页触达",
    )
)

SKILL_FLOW_XHS = _register(
    AgentStrategy(
        id="skill-flow-xiaohongshu",
        platform="xiaohongshu",
        label="类人分步（Skill）",
        description="Skill 独立分步执行：搜索框输入关键词，监听浏览器正常请求入库，再按规则触达",
        profile_id="task-xiaohongshu-skill-flow",
        execution_mode="skill_flow",
        crawl_skill_id="xhs-keyword-comments",
        inherit_base_prompt=True,
        inherit_workflow_prompt=True,
        inherit_experience_prompt=False,
        exclude_rule_ids=[],
        system_prompt=(
            "你是小红书获客 **任务专用** 智能体（类人分步 Skill 策略）。\n"
            "纪律：\n"
            "1. 抓取由 Supervisor 调用 xhs-keyword-comments（builtin）；搜索必须由 Skill 在搜索框输入关键词触发\n"
            "2. 触达使用 reply-comment / follow-user\n"
            "3. 触达前 query_stats 查配额\n"
            "4. 禁止 JS 直调搜索接口、禁止 browser_goto 搜索页、禁止拼接搜索 URL"
        ),
        ui_flow_runtime=False,
        bootstrap_crawl=False,
        inline_ui_outreach=False,
        supervisor_plan_only=True,
        crawl_purpose="类人搜索框输入关键词，监听浏览器 search/comment 请求并批量抓评论入库",
    )
)

_PLATFORM_DEFAULTS: dict[str, str] = {
    "douyin": SKILL_FLOW_DOUYIN.id,
    "xiaohongshu": SKILL_FLOW_XHS.id,
    "kuaishou": "skill-flow-kuaishou",
}

# 快手类人分步（无独立流程时默认 Skill 分步）
SKILL_FLOW_KS = _register(
    AgentStrategy(
        id="skill-flow-kuaishou",
        platform="kuaishou",
        label="类人分步（Skill）",
        description="Skill 独立分步执行：搜索框输入关键词，监听浏览器正常请求入库，再按规则触达",
        profile_id="task-kuaishou-skill-flow",
        execution_mode="skill_flow",
        crawl_skill_id="kuaishou-keyword-comments",
        inherit_base_prompt=True,
        inherit_workflow_prompt=True,
        inherit_experience_prompt=False,
        exclude_rule_ids=[],
        system_prompt=(
            "你是快手获客 **任务专用** 智能体（类人分步 Skill 策略）。\n"
            "纪律：\n"
            "1. 抓取由 Supervisor 调用 kuaishou-keyword-comments（builtin）；搜索必须由 Skill 在搜索框输入关键词触发\n"
            "2. 触达使用 reply-comment / send-dm / follow-user\n"
            "3. 触达前 query_stats 查配额\n"
            "4. 禁止 JS 直调搜索接口、禁止 browser_goto 搜索页、禁止拼接搜索 URL"
        ),
        ui_flow_runtime=False,
        bootstrap_crawl=False,
        inline_ui_outreach=False,
        supervisor_plan_only=True,
        crawl_purpose="类人搜索框输入关键词，监听浏览器 search/comment 请求并批量抓评论入库",
    )
)


def list_strategies(*, platform: str | None = None) -> list[dict[str, Any]]:
    plat = (platform or "").strip().lower()
    items = list(_BUILTIN.values())
    if plat:
        items = [s for s in items if s.platform == plat]
    default_id = _PLATFORM_DEFAULTS.get(plat) if plat else None
    return [
        {
            "id": s.id,
            "platform": s.platform,
            "label": s.label,
            "description": s.description,
            "profile_id": s.profile_id,
            "execution_mode": s.execution_mode,
            "crawl_skill_id": s.crawl_skill_id,
            "is_default": s.id == default_id,
        }
        for s in sorted(items, key=lambda x: (x.platform, x.id != default_id, x.label))
    ]


def resolve_agent_strategy(strategy_id: str | None, *, platform: str) -> AgentStrategy:
    """解析策略 ID；缺省或未知时回退平台默认。"""
    plat = (platform or "douyin").strip().lower()
    sid = (strategy_id or "").strip()
    if sid and sid in _BUILTIN:
        st = _BUILTIN[sid]
        if st.platform == plat:
            return st
    default_id = _PLATFORM_DEFAULTS.get(plat) or SKILL_FLOW_DOUYIN.id
    if default_id in _BUILTIN:
        return _BUILTIN[default_id]
    return SKILL_FLOW_DOUYIN


def default_strategy_for_platform(platform: str) -> AgentStrategy:
    return resolve_agent_strategy(None, platform=platform)


def strategy_by_profile_id(profile_id: str) -> AgentStrategy | None:
    pid = (profile_id or "").strip()
    for st in _BUILTIN.values():
        if st.profile_id == pid:
            return st
    return None


def parse_strategy_from_payload(payload: dict[str, Any] | None, *, platform: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
    for key in ("agent_strategy", "strategy", "crawl_strategy"):
        val = payload.get(key) or spec.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return None
