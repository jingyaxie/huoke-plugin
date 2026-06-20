"""外部系统集成：任务意图注册、参数归一化、创建 Agent Job。

外部系统（AISales / PC）只需按 capabilities 传 intent + scope；
字段映射、brief 补全、message 生成均在 Huoke 内完成。
"""
from __future__ import annotations

from typing import Any

from app.schemas.external_task import (
    ExternalTaskCapabilitiesOut,
    ExternalTaskCreateRequest,
    ExternalTaskFieldOption,
    ExternalTaskFieldSpec,
    ExternalTaskIntentSpec,
)
from app.services.manual_acquisition_service import enrich_manual_acquisition_brief

PUBLISH_TIME_RANGE_TO_DAYS: dict[str, int | None] = {
    "unlimited": None,
    "1d": 1,
    "3d": 3,
    "7d": 7,
    "180d": 180,
}

INTENT_SPECS: tuple[ExternalTaskIntentSpec, ...] = (
    ExternalTaskIntentSpec(
        intent="keyword_auto",
        label="关键词自动获客",
        description="按关键词搜索视频并抓取评论，循环触达。",
        lead_task_types=["home_auto"],
        default_comment_days=3,
        scope_fields=[
            ExternalTaskFieldSpec(key="keyword", type="string", required=True, label="关键词"),
            ExternalTaskFieldSpec(key="region", type="string", label="地区"),
            ExternalTaskFieldSpec(key="target_count", type="integer", required=True, label="目标精准线索数"),
            ExternalTaskFieldSpec(
                key="crawl_video_limit",
                type="integer",
                label="单批扫描视频上限",
                description="可选。每轮最多浏览多少个视频；与目标精准线索数无关。未填时一体化模式默认按较大上限续扫。",
            ),
            ExternalTaskFieldSpec(key="comment_days", type="integer", label="评论天数"),
            ExternalTaskFieldSpec(key="publish_time_range", type="string", label="视频发布时间筛选"),
            ExternalTaskFieldSpec(key="repeat_mode", type="string", label="循环模式"),
            ExternalTaskFieldSpec(key="round_target_count", type="integer", label="每轮目标"),
            ExternalTaskFieldSpec(key="max_rounds", type="integer", label="最大轮次"),
        ],
    ),
    ExternalTaskIntentSpec(
        intent="account_home",
        label="账号主页手动获客",
        description="浏览指定账号主页，获取视频列表并抓取评论触达。",
        lead_task_types=["home_manual"],
        default_comment_days=3,
        scope_fields=[
            ExternalTaskFieldSpec(key="input_url", type="string", required=True, label="主页链接"),
            ExternalTaskFieldSpec(key="comment_days", type="integer", label="评论天数"),
            ExternalTaskFieldSpec(key="publish_time_range", type="string", label="视频发布时间筛选"),
            ExternalTaskFieldSpec(key="crawl_video_limit", type="integer", label="扫描视频数"),
        ],
    ),
    ExternalTaskIntentSpec(
        intent="single_video",
        label="单视频手动获客",
        description="从指定单条视频链接抓取评论并触达。",
        lead_task_types=["video_manual"],
        default_comment_days=3,
        scope_fields=[
            ExternalTaskFieldSpec(key="input_url", type="string", required=True, label="视频链接"),
            ExternalTaskFieldSpec(key="comment_days", type="integer", label="评论天数"),
            ExternalTaskFieldSpec(key="publish_time_range", type="string", label="视频发布时间筛选"),
        ],
    ),
)

INTENT_BY_LEAD_TASK_TYPE = {
    lead_type: spec.intent
    for spec in INTENT_SPECS
    for lead_type in spec.lead_task_types
}

FIELD_OPTIONS: dict[str, list[ExternalTaskFieldOption]] = {
    "publish_time_range": [
        ExternalTaskFieldOption(value="unlimited", label="不限"),
        ExternalTaskFieldOption(value="1d", label="1天内"),
        ExternalTaskFieldOption(value="3d", label="3天内"),
        ExternalTaskFieldOption(value="7d", label="1周内"),
        ExternalTaskFieldOption(value="180d", label="半年内"),
    ],
    "comment_days": [
        ExternalTaskFieldOption(value="3", label="3天"),
        ExternalTaskFieldOption(value="5", label="5天"),
        ExternalTaskFieldOption(value="7", label="7天"),
        ExternalTaskFieldOption(value="0", label="不限"),
    ],
}


def get_external_capabilities() -> ExternalTaskCapabilitiesOut:
    from app.services.lead_evaluation_templates import list_evaluation_templates

    return ExternalTaskCapabilitiesOut(
        intents=list(INTENT_SPECS),
        field_options=FIELD_OPTIONS,
        evaluation_fields=[
            ExternalTaskFieldSpec(key="template_id", type="string", label="行业模板"),
            ExternalTaskFieldSpec(key="target_customer", type="string", label="目标客户"),
            ExternalTaskFieldSpec(key="accept_description", type="string", label="有效线索描述"),
            ExternalTaskFieldSpec(key="reject_description", type="string", label="排除描述"),
            ExternalTaskFieldSpec(key="precise_threshold", type="number", label="精准度阈值"),
            ExternalTaskFieldSpec(key="outreach_threshold", type="number", label="触达阈值"),
        ],
        evaluation_templates=list_evaluation_templates(),
    )


def resolve_intent(*, intent: str | None, lead_task_type: str | None = None) -> str:
    normalized = str(intent or "").strip().lower()
    if normalized in {spec.intent for spec in INTENT_SPECS}:
        return normalized
    mapped = INTENT_BY_LEAD_TASK_TYPE.get(str(lead_task_type or "").strip())
    if mapped:
        return mapped
    raise ValueError("unsupported_intent")


def _map_publish_time_range(value: Any) -> int | None:
    raw = str(value or "unlimited").strip().lower()
    return PUBLISH_TIME_RANGE_TO_DAYS.get(raw, PUBLISH_TIME_RANGE_TO_DAYS["unlimited"])


def _normalize_constraints(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    constraints: dict[str, Any] = dict(raw)
    alias_map = {
        "comment_dm_interval_seconds_min": "interval_min",
        "comment_dm_interval_seconds_max": "interval_max",
        "comment_dm_percentage": "comment_ratio",
        "follow_per_day": "daily_follow_limit",
        "dm_per_day": "daily_dm_limit",
    }
    for src, dst in alias_map.items():
        if src in constraints and dst not in constraints:
            constraints[dst] = constraints[src]
    return constraints


def normalize_external_create(request: ExternalTaskCreateRequest) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """将外部创建请求归一化为 (message, config, correlation)。"""
    intent = resolve_intent(intent=request.intent)
    scope = request.scope.model_dump(exclude_none=True)
    outreach = request.outreach.model_dump(exclude_none=True)
    constraints = _normalize_constraints(outreach.get("constraints"))

    input_url = str(scope.get("input_url") or "").strip()
    if input_url and intent in {"single_video", "account_home"}:
        from app.services.manual_acquisition_service import reconcile_manual_acquisition_mode

        intent = reconcile_manual_acquisition_mode(intent, input_url, request.platform)

    acquisition_mode = {
        "keyword_auto": "keyword_auto",
        "single_video": "single_video",
        "account_home": "account_home",
    }[intent]

    config: dict[str, Any] = {
        "intent": intent,
        "acquisition_mode": acquisition_mode,
        "platform": request.platform,
        "task_name": request.name,
        "execution": "huoke_agent",
        "source": "huoke_agent",
        "acquisition_route": "huoke",
    }

    keyword = str(scope.get("keyword") or "").strip()
    region = str(scope.get("region") or "").strip()
    target_count = scope.get("target_count")
    comment_days = scope.get("comment_days")
    publish_days = _map_publish_time_range(scope.get("publish_time_range"))

    if keyword:
        config["keyword"] = keyword
    if region:
        config["region"] = region
    if target_count is not None:
        config["target_count"] = int(target_count)
    if comment_days is not None:
        config["comment_days"] = int(comment_days)
    if publish_days is not None:
        config["video_publish_days"] = publish_days
        config["publish_time_range"] = scope.get("publish_time_range")
    if scope.get("repeat_mode"):
        config["repeat_mode"] = str(scope["repeat_mode"])
    if scope.get("round_target_count") is not None:
        config["round_target_count"] = int(scope["round_target_count"])
    if scope.get("max_rounds") is not None:
        config["max_rounds"] = int(scope["max_rounds"])
    if scope.get("crawl_video_limit") is not None:
        config["crawl_video_limit"] = int(scope["crawl_video_limit"])

    if input_url:
        config["input_url"] = input_url
        if intent == "single_video":
            config["video_url"] = input_url
        elif intent == "account_home":
            config["profile_url"] = input_url

    if constraints:
        config["constraints"] = constraints

    if request.evaluation is not None:
        config["evaluation"] = request.evaluation.model_dump(exclude_none=True)

    if request.crawl is not None and request.crawl.headless is not None:
        config["crawl"] = {"headless": bool(request.crawl.headless)}
    if request.crawl is not None and request.crawl.force_refresh is not None:
        config.setdefault("crawl", {})
        config["crawl"]["force_refresh"] = bool(request.crawl.force_refresh)
        config["force_refresh"] = bool(request.crawl.force_refresh)

    for key in ("reply_templates", "dm_templates", "reply_template", "dm_template"):
        val = outreach.get(key)
        if val is None or val == "" or val == []:
            continue
        config[key] = val
        config.setdefault("constraints", {})[key] = val

    correlation = request.correlation.model_dump(exclude_none=True)
    config["correlation"] = correlation

    message = _build_message(
        intent=intent,
        name=request.name,
        platform=request.platform,
        config=config,
        input_url=input_url or None,
    )
    return message, config, correlation


def _build_message(
    *,
    intent: str,
    name: str,
    platform: str,
    config: dict[str, Any],
    input_url: str | None,
) -> str:
    comment_days = config.get("comment_days")
    publish_days = config.get("video_publish_days")
    target = config.get("target_count")
    keyword = config.get("keyword") or name
    region = config.get("region") or ""

    if intent == "single_video" and input_url:
        return (
            f"{name}：从单条视频链接采集评论并触达。"
            f" 平台={platform}，链接={input_url}，评论窗口={comment_days or '不限'}天，"
            f"视频发布筛选={publish_days or '不限'}天。"
        )
    if intent == "account_home" and input_url:
        return (
            f"{name}：从指定账号主页采集评论并触达。"
            f" 平台={platform}，主页={input_url}，评论窗口={comment_days or '不限'}天，"
            f"视频发布筛选={publish_days or '不限'}天。"
        )
    return (
        f"{name}：关键词获客并触达。"
        f" 平台={platform}，关键词={keyword}，地区={region or '不限'}，"
        f"目标线索={target or '默认'}，评论窗口={comment_days or 3}天。"
    )


def enrich_brief_from_external_config(brief, config: dict[str, Any]):
    """手动获客 brief 补全（供 submit_async 复用）。"""
    mode = str(config.get("acquisition_mode") or "").strip().lower()
    if mode in {"single_video", "account_home"}:
        enriched = enrich_manual_acquisition_brief(brief, config)
        target = config.get("target_count") or config.get("target_leads")
        if target is not None:
            try:
                enriched.goals["target_leads"] = int(target)
            except (TypeError, ValueError):
                pass
        return enriched
    target = config.get("target_count") or config.get("requested_target") or config.get("target_leads")
    if target is not None:
        try:
            brief.goals["target_leads"] = int(target)
        except (TypeError, ValueError):
            pass
    if config.get("force_refresh"):
        brief.goals["force_refresh"] = True
    if config.get("video_publish_days") is not None:
        brief.goals["video_publish_days"] = int(config["video_publish_days"])
    if config.get("comment_days") is not None:
        brief.goals["comment_days"] = int(config["comment_days"])
    crawl = config.get("crawl")
    if isinstance(crawl, dict):
        if crawl.get("headless") is True:
            brief.goals["show_browser"] = False
            brief.goals["headless"] = True
        elif crawl.get("headless") is False:
            brief.goals["show_browser"] = True
            brief.goals["headless"] = False
    elif config.get("headless") is True:
        brief.goals["show_browser"] = False
        brief.goals["headless"] = True
    elif config.get("headless") is False:
        brief.goals["show_browser"] = True
        brief.goals["headless"] = False

    from app.core.antibot import headless_for_platform
    from app.core.config import get_settings

    settings = get_settings()
    platform = str(config.get("platform") or brief.platform or "douyin")
    if settings.desktop_mode and not headless_for_platform(settings, platform):
        brief.goals["show_browser"] = True
        brief.goals["headless"] = False

    return brief
