from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.agent_llm import resolve_default_provider
from app.services.ai_client import AIClientFactory
from app.services.agent_strategy import parse_strategy_from_payload, resolve_agent_strategy
from app.services.task_skill_playbook import (
    attach_skill_playbook_to_brief_md,
    build_allowed_skills,
    build_skill_playbook_md,
    skill_catalog_for_llm,
)

_CRAWL_VIDEO_LIMIT_KEYS = ("crawl_video_limit", "video_limit", "content_limit", "limit", "video_limit_per_batch")
_DEFAULT_CRAWL_VIDEO_LIMIT = 5


def normalize_outreach_interval_constraints(dest: dict[str, Any]) -> None:
    """把 interval_min/max 同步为 interval_*_sec，供 Supervisor 与存储一致读取。"""
    if dest.get("interval_min_sec") is None and dest.get("interval_min") is not None:
        dest["interval_min_sec"] = dest["interval_min"]
    if dest.get("interval_max_sec") is None and dest.get("interval_max") is not None:
        dest["interval_max_sec"] = dest["interval_max"]
    if dest.get("interval_min") is None and dest.get("interval_min_sec") is not None:
        dest["interval_min"] = dest["interval_min_sec"]
    if dest.get("interval_max") is None and dest.get("interval_max_sec") is not None:
        dest["interval_max"] = dest["interval_max_sec"]


class TaskBrief(BaseModel):
    """Supervisor 任务简报：MD 正文 + 结构化目标。"""

    title: str = "获客任务"
    brief_md: str = ""
    platform: str = "douyin"
    keyword: str | None = None
    region: str | None = None
    goals: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_criteria: str = ""
    allowed_skills: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.0
    llm_available: bool = False
    llm_fallback: bool = True
    agent_strategy: str | None = None
    agent_profile_id: str | None = None


def _explicit_crawl_video_limit_from_payload(payload: dict[str, Any] | None) -> int | None:
    src = payload if isinstance(payload, dict) else {}
    for key in _CRAWL_VIDEO_LIMIT_KEYS:
        val = src.get(key)
        if val is None or val == "":
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return None


def _crawl_video_limit_from_payload(
    payload: dict[str, Any] | None,
    *,
    default: int = _DEFAULT_CRAWL_VIDEO_LIMIT,
    omit_default_for_standalone: bool = False,
    agent_strategy: str | None = None,
) -> int | None:
    explicit = _explicit_crawl_video_limit_from_payload(payload)
    if explicit is not None:
        return explicit
    if omit_default_for_standalone:
        from app.services.agent_strategy.registry import STANDALONE_BROWSE_DOUYIN

        sid = str(agent_strategy or "").strip()
        if sid == STANDALONE_BROWSE_DOUYIN.id or sid == "standalone-browse-douyin":
            return None
    return default


def is_skill_flow_brief(brief: TaskBrief) -> bool:
    """类人分步：搜索框输入关键词，监听浏览器正常请求，再独立触达。"""
    if str(brief.goals.get("execution_mode") or "") == "skill_flow":
        return True
    strategy = str(brief.agent_strategy or brief.goals.get("agent_strategy") or "").strip()
    return strategy.startswith("skill-flow")


def _extract_json_from_message(message: str) -> dict[str, Any] | None:
    text = (message or "").strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def _truthy_cli_flag(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_skill_cli_args(message: str) -> dict[str, str]:
    """解析 /douyin-keyword-comments key=value 形式的 pipeline 消息头。"""
    first = (message or "").strip().splitlines()[0].strip() if message else ""
    if not first.startswith("/"):
        return {}
    tokens = first.split()[1:]
    parsed: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            parsed[key] = value
    return parsed


def enrich_brief_from_skill_message(brief: TaskBrief, message: str) -> TaskBrief:
    args = _parse_skill_cli_args(message)
    if not args:
        return brief
    if args.get("keyword") and not brief.keyword:
        brief.keyword = args["keyword"]
    if args.get("region") and not brief.region:
        brief.region = args["region"]
    show_browser_flag = _truthy_cli_flag(args.get("show_browser"))
    headless_flag = _truthy_cli_flag(args.get("headless"))
    if show_browser_flag is not None:
        brief.goals["show_browser"] = show_browser_flag
        brief.goals["headless"] = not show_browser_flag
    elif headless_flag is not None:
        brief.goals["headless"] = headless_flag
        brief.goals["show_browser"] = not headless_flag
    force_refresh = _truthy_cli_flag(args.get("force_refresh"))
    if force_refresh is not None:
        brief.goals["force_refresh"] = force_refresh
    return brief


def _keyword_from_text(text: str) -> str | None:
    quoted = re.search(r"[「『\"']([^」』\"']{2,40})[」』\"']", text)
    if quoted:
        return quoted.group(1).strip()
    for pattern in (r"关键词[：:]\s*(\S+)", r"搜索[：:]\s*(\S+)"):
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _fallback_brief(message: str, *, agent_strategy: str | None = None) -> TaskBrief:
    text = (message or "").strip()
    payload = _extract_json_from_message(text)
    spec = payload.get("spec") if isinstance(payload, dict) and isinstance(payload.get("spec"), dict) else {}
    crawl = spec.get("crawl") if isinstance(spec.get("crawl"), dict) else {}

    keyword = (
        spec.get("keyword")
        or (payload or {}).get("keyword")
        or (payload or {}).get("product_keyword")
        or _keyword_from_text(text)
    )
    platform = str(spec.get("platform") or (payload or {}).get("platform") or "douyin").strip().lower()
    strategy_id = agent_strategy or parse_strategy_from_payload(payload, platform=platform)
    strategy = resolve_agent_strategy(strategy_id, platform=platform)
    region = spec.get("region") or (payload or {}).get("region")
    target_leads = (
        crawl.get("target_leads")
        or (payload or {}).get("target_count")
        or (payload or {}).get("requested_target")
        or (payload or {}).get("target_leads")
        or 50
    )
    comment_days = crawl.get("comment_days") or (payload or {}).get("comment_days") or 3
    video_publish_days = crawl.get("video_publish_days") or (payload or {}).get("video_publish_days")
    if video_publish_days is None and (payload or {}).get("publish_time_range"):
        from app.services.external_task_service import _map_publish_time_range

        video_publish_days = _map_publish_time_range((payload or {}).get("publish_time_range"))
    crawl_video_limit = _crawl_video_limit_from_payload(
        {**(payload or {}), **crawl},
        omit_default_for_standalone=True,
        agent_strategy=strategy.id,
    )
    repeat_mode = (payload or {}).get("repeat_mode") or crawl.get("repeat_mode")
    round_target = (payload or {}).get("round_target_count") or crawl.get("round_target_count")
    max_rounds = (payload or {}).get("max_rounds") or crawl.get("max_rounds")
    title = (
        spec.get("task_name")
        or (payload or {}).get("task_name")
        or (payload or {}).get("name")
        or (f"{region or ''}{keyword or '获客'}任务").strip()
    )

    brief_md = f"""# {title}

## 目标
- 平台：{platform}
- 关键词：{keyword or '（待补充）'}
- 地区：{region or '不限'}
- 目标线索数：{target_leads}
- 评论抓取窗口：近 {comment_days} 天

## 策略原则
1. 先抓取关键词相关视频评论并入库
2. 根据互动台账配额与去重状态选择触达方式（评论 / 私信 / 关注）
3. 每轮根据数据快照重新决策，直至达成目标或配额耗尽

{build_skill_playbook_md(platform, strategy=strategy)}

## 原始输入
{text[:2000]}
"""
    allowed = build_allowed_skills(platform, strategy=strategy)
    plat = platform if platform in {"douyin", "xiaohongshu", "kuaishou"} else "douyin"
    return TaskBrief(
        title=str(title),
        brief_md=brief_md,
        platform=plat,
        keyword=str(keyword) if keyword else None,
        region=str(region) if region else None,
        agent_strategy=strategy.id,
        agent_profile_id=strategy.profile_id,
        goals={
            "target_leads": int(target_leads) if target_leads else 50,
            "comment_days": int(comment_days) if comment_days else 3,
            **({"video_publish_days": int(video_publish_days)} if video_publish_days else {}),
            **({"crawl_video_limit": int(crawl_video_limit)} if crawl_video_limit is not None else {}),
            **({"repeat_mode": str(repeat_mode)} if repeat_mode else {}),
            **({"round_target_count": int(round_target)} if round_target else {}),
            **({"max_rounds": int(max_rounds)} if max_rounds else {}),
            "execution_mode": strategy.execution_mode,
            "inline_ui_outreach": strategy.inline_ui_outreach,
            "ui_first": strategy.ui_first,
            "agent_strategy": strategy.id,
            "supervisor_plan_only": strategy.supervisor_plan_only,
        },
        constraints={
            "daily_reply_limit": 30,
            "daily_follow_limit": 3,
            "daily_dm_limit": 3,
        },
        success_criteria=f"累计有效线索 ≥ {target_leads}",
        allowed_skills=allowed,
        reasoning="大模型未配置，已使用规则回退生成任务简报",
        confidence=0.35,
        llm_available=False,
        llm_fallback=True,
    )


def _finalize_brief(brief: TaskBrief, *, agent_strategy: str | None = None) -> TaskBrief:
    """附加规范 Skill 白名单，确保 brief_md 与 allowed_skills 一致。"""
    platform = brief.platform or "douyin"
    strategy_id = agent_strategy or brief.agent_strategy or brief.goals.get("agent_strategy")
    strategy = resolve_agent_strategy(str(strategy_id) if strategy_id else None, platform=platform)
    brief.agent_strategy = strategy.id
    brief.agent_profile_id = brief.agent_profile_id or strategy.profile_id
    brief.goals.setdefault("execution_mode", strategy.execution_mode)
    brief.goals.setdefault("inline_ui_outreach", strategy.inline_ui_outreach)
    brief.goals.setdefault("ui_first", strategy.ui_first)
    brief.goals.setdefault("agent_strategy", strategy.id)
    if strategy.supervisor_plan_only or is_skill_flow_brief(brief):
        brief.goals.setdefault("supervisor_plan_only", True)
    brief.brief_md = attach_skill_playbook_to_brief_md(brief.brief_md, platform, strategy=strategy)
    brief.allowed_skills = build_allowed_skills(platform, strategy=strategy)
    return brief


async def generate_task_brief(
    message: str,
    *,
    settings: Settings,
    tenant_id: str,
    provider: str = "deepseek",
    agent_strategy: str | None = None,
) -> TaskBrief:
    """LLM 生成 task_brief.md；无 LLM 时规则回退。"""
    text = (message or "").strip()
    if not text:
        return _fallback_brief("通用浏览器任务")

    resolved = resolve_default_provider(settings)
    factory = AIClientFactory(settings)
    client = factory.llm_client()
    if client is None:
        payload = _extract_json_from_message(text)
        sid = agent_strategy or parse_strategy_from_payload(payload, platform="douyin")
        return _finalize_brief(_fallback_brief(text, agent_strategy=sid), agent_strategy=sid)

    model = factory.llm_model()
    system = (
        "你是获客任务规划师。根据用户输入生成任务简报。"
        "只输出一个 JSON 对象，不要 markdown 代码块。字段："
        "title(string), brief_md(string, Markdown 正文，必须含：目标/约束/策略/终止条件；"
        "可简述执行顺序，但 Skill 白名单由系统追加，勿自行编造未提供的 Skill), "
        "platform(douyin|xiaohongshu|kuaishou), keyword(string|null), region(string|null), "
        "goals(object, 含 target_leads/comment_days 等), "
        "constraints(object, 含 daily_reply_limit/daily_follow_limit/daily_dm_limit), "
        "success_criteria(string), reasoning(string), confidence(0-1)。"
        "Supervisor 只能使用 skill_catalog 中列出的 supervisor_action。"
    )
    user = json.dumps(
        {
            "tenant_id": tenant_id,
            "user_message": text,
            "skill_catalog": skill_catalog_for_llm("douyin"),
        },
        ensure_ascii=False,
    )

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw)
        if not isinstance(data, dict):
            payload = _extract_json_from_message(text)
            sid = agent_strategy or parse_strategy_from_payload(payload, platform="douyin")
            return _finalize_brief(_fallback_brief(text, agent_strategy=sid), agent_strategy=sid)
        platform = str(data.get("platform") or "douyin")
        payload = _extract_json_from_message(text)
        sid = agent_strategy or parse_strategy_from_payload(payload, platform=platform)
        brief = TaskBrief(
            title=str(data.get("title") or "获客任务"),
            brief_md=str(data.get("brief_md") or ""),
            platform=str(data.get("platform") or "douyin"),
            keyword=data.get("keyword"),
            region=data.get("region"),
            goals=data.get("goals") if isinstance(data.get("goals"), dict) else {},
            constraints=data.get("constraints") if isinstance(data.get("constraints"), dict) else {},
            success_criteria=str(data.get("success_criteria") or ""),
            reasoning=str(data.get("reasoning") or ""),
            confidence=float(data.get("confidence") or 0.8),
            llm_available=True,
            llm_fallback=False,
        )
        if not brief.brief_md:
            brief.brief_md = f"# {brief.title}\n\n{brief.success_criteria or text[:500]}"
        return _finalize_brief(brief, agent_strategy=sid)
    except Exception:
        payload = _extract_json_from_message(text)
        sid = agent_strategy or parse_strategy_from_payload(payload, platform="douyin")
        return _finalize_brief(_fallback_brief(text, agent_strategy=sid), agent_strategy=sid)


def enrich_brief_from_task_payload(brief: TaskBrief, payload: dict[str, Any] | None) -> tuple[TaskBrief, list[str]]:
    """把任务 JSON 中的 matching/outreach/crawl 等结构化字段合并进 brief。"""
    if not isinstance(payload, dict):
        return brief, []

    unmapped: list[str] = []

    target = payload.get("target_leads", payload.get("target_count"))
    if target is not None and brief.goals.get("target_leads") is None:
        try:
            brief.goals["target_leads"] = int(target)
        except (TypeError, ValueError):
            pass
    repeat_mode = payload.get("repeat_mode")
    if repeat_mode is not None:
        brief.goals["repeat_mode"] = str(repeat_mode)
        brief.constraints["repeat_mode"] = str(repeat_mode)
    for key in ("round_target_count", "round_target_leads", "max_rounds"):
        val = payload.get(key)
        if val is None:
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        brief.goals[key] = n
        brief.constraints[key] = n
    success_criteria = str(payload.get("success_criteria") or "").strip()
    if success_criteria and not brief.success_criteria:
        brief.success_criteria = success_criteria

    evaluation_raw = payload.get("evaluation")
    if isinstance(evaluation_raw, dict) and evaluation_raw:
        from app.services.lead_evaluation_service import evaluation_draft_from_payload
        from app.services.lead_evaluation_templates import resolve_evaluation_template

        draft = evaluation_draft_from_payload(evaluation_raw)
        template_id = evaluation_raw.get("template_id")
        if template_id:
            draft = {**resolve_evaluation_template(str(template_id)), **draft}
        brief.constraints["evaluation_draft"] = draft

    matching = payload.get("matching")
    if isinstance(matching, dict):
        region_filter = matching.get("region_filter")
        if region_filter and not brief.region:
            brief.region = str(region_filter).strip()

    outreach = payload.get("outreach_strategy")
    if not isinstance(outreach, dict):
        outreach = payload.get("outreach") if isinstance(payload.get("outreach"), dict) else None
    if isinstance(outreach, dict):
        reply_template = str(outreach.get("reply_template") or "").strip()
        reply_tone = str(outreach.get("reply_tone") or "").strip()
        dm_template = str(outreach.get("dm_template") or "").strip()
        reply_templates = outreach.get("reply_templates")
        dm_templates = outreach.get("dm_templates")
        if isinstance(reply_templates, list) and reply_templates:
            texts = [str(item).strip() for item in reply_templates if str(item).strip()]
            if texts:
                brief.constraints["reply_templates"] = texts
        if isinstance(dm_templates, list) and dm_templates:
            texts = [str(item).strip() for item in dm_templates if str(item).strip()]
            if texts:
                brief.constraints["dm_templates"] = texts
        if reply_template:
            brief.constraints["reply_template"] = reply_template
            brief.constraints["actions_on_match"] = [{"type": "reply", "template": reply_template}]
        elif reply_tone:
            brief.constraints["reply_template"] = f"{{{{nickname}}}}，{reply_tone}"
            brief.constraints["actions_on_match"] = [{"type": "reply", "template": brief.constraints["reply_template"]}]
        if dm_template:
            brief.constraints["dm_template"] = dm_template
        priority = outreach.get("priority")
        if isinstance(priority, list) and priority:
            brief.constraints["outreach_priority"] = [str(p) for p in priority if str(p).strip()]
        if outreach.get("follow_before_dm") is not None:
            brief.constraints["follow_before_dm"] = bool(outreach.get("follow_before_dm"))
        if outreach.get("skip_replied_comments") is not None:
            brief.constraints["skip_replied_comments"] = bool(outreach.get("skip_replied_comments"))

    termination = payload.get("termination")
    if isinstance(termination, dict):
        for key in ("success_when", "suspend_when", "resume_next_day"):
            val = termination.get(key)
            if val is not None:
                brief.constraints[f"termination_{key}"] = val

    crawl = payload.get("crawl")
    if isinstance(crawl, dict):
        if crawl.get("repeat_mode") is not None:
            brief.goals["repeat_mode"] = str(crawl.get("repeat_mode"))
            brief.constraints["repeat_mode"] = str(crawl.get("repeat_mode"))
        for key in ("round_target_count", "round_target_leads", "max_rounds"):
            val = crawl.get(key)
            if val is not None:
                brief.goals[key] = int(val)
                brief.constraints[key] = int(val)
        if crawl.get("force_refresh") is not None:
            brief.goals["force_refresh"] = bool(crawl.get("force_refresh"))
        if crawl.get("cache_ttl_hours") is not None:
            brief.goals["cache_ttl_hours"] = float(crawl.get("cache_ttl_hours"))
        explicit_limit = _explicit_crawl_video_limit_from_payload(crawl)
        if explicit_limit is not None:
            brief.goals["crawl_video_limit"] = explicit_limit
        if crawl.get("headless") is True:
            brief.goals["show_browser"] = False
        elif crawl.get("headless") is False:
            brief.goals["show_browser"] = True

    for src, dest in (
        (payload.get("goals"), brief.goals),
        (payload.get("constraints"), brief.constraints),
    ):
        if not isinstance(src, dict):
            continue
        for key, val in src.items():
            if val is None:
                continue
            if key not in dest:
                dest[key] = val
            if key in _CRAWL_VIDEO_LIMIT_KEYS and brief.goals.get("crawl_video_limit") is None:
                try:
                    n = int(val)
                except (TypeError, ValueError):
                    continue
                if n > 0:
                    brief.goals["crawl_video_limit"] = n

    normalize_outreach_interval_constraints(brief.constraints)
    if isinstance(brief.goals.get("ui_timing"), dict):
        normalize_outreach_interval_constraints(brief.goals["ui_timing"])

    known_top = {
        "task_name",
        "platform",
        "region",
        "keyword",
        "intent",
        "account_id",
        "target_count",
        "target_leads",
        "repeat_mode",
        "round_target_count",
        "round_target_leads",
        "max_rounds",
        "crawl_video_limit",
        "video_limit",
        "content_limit",
        "limit",
        "video_limit_per_batch",
        "success_criteria",
        "goals",
        "constraints",
        "matching",
        "evaluation",
        "evaluation_draft",
        "outreach_strategy",
        "termination",
        "crawl",
        "notes",
        "agent_strategy",
        "strategy",
    }
    for key in payload:
        if key not in known_top and key not in brief.goals and key not in brief.constraints:
            unmapped.append(str(key))

    from app.services.manual_acquisition_service import enrich_manual_acquisition_brief

    brief = enrich_manual_acquisition_brief(brief, payload)

    return brief, unmapped
