"""外部任务创建前预检：Sidecar 是否可执行、编排/工具/评估是否就绪。"""
from __future__ import annotations

from typing import Any, Literal

from app.core.config import Settings
from app.platforms.registry import get_session_store
from app.schemas.external_task import (
    ExternalTaskCreateRequest,
    ExternalTaskPreflightCheck,
    ExternalTaskPreflightEvaluationPreview,
    ExternalTaskPreflightOrchestrationPreview,
    ExternalTaskPreflightOut,
)
from app.services.agent_llm import resolve_default_provider
from app.services.agent_strategy import default_strategy_for_platform, resolve_agent_strategy
from app.services.ai_client import AIClientFactory
from app.services.external_task_service import INTENT_SPECS, normalize_external_create, resolve_intent
from app.services.lead_evaluation_service import (
    build_rule_based_spec,
    evaluation_draft_from_payload,
    evaluation_preview_text,
)
from app.services.platform_account_store import _is_platform_cookie_ready
from app.services.skill_store import SkillStore, resolve_skill_id
from app.services.task_brief_service import TaskBrief
from app.services.task_config_update_service import update_task_config
from app.services.task_execution_plan import build_supervisor_execution_plan
from app.services.standalone_browse_adapter import STANDALONE_PIPELINE, is_standalone_browse_brief
from app.services.supervisor_crawl_helpers import CRAWL_SUPERVISOR_ACTIONS
from app.services.task_skill_playbook import skill_id_for_supervisor_action

INTERNAL_SUPERVISOR_ACTIONS = frozenset(
    {"evaluate_leads", "query_stats", "query_comments", "complete", "check_login"},
)


def _check(
    *,
    check_id: str,
    label: str,
    status: Literal["ok", "warning", "error"],
    message: str,
    blocking: bool = False,
) -> ExternalTaskPreflightCheck:
    return ExternalTaskPreflightCheck(
        id=check_id,
        label=label,
        status=status,
        message=message,
        blocking=blocking and status == "error",
    )


def _validate_scope(request: ExternalTaskCreateRequest) -> ExternalTaskPreflightCheck | None:
    intent = resolve_intent(intent=request.intent)
    spec = next((item for item in INTENT_SPECS if item.intent == intent), None)
    if spec is None:
        return _check(
            check_id="scope",
            label="任务参数",
            status="error",
            message=f"不支持的任务意图：{intent}",
            blocking=True,
        )
    scope = request.scope.model_dump(exclude_none=True)
    missing: list[str] = []
    for field in spec.scope_fields:
        if not field.required:
            continue
        val = scope.get(field.key)
        if val is None or val == "" or val == []:
            missing.append(field.label or field.key)
    if missing:
        return _check(
            check_id="scope",
            label="任务参数",
            status="error",
            message=f"缺少必填项：{'、'.join(missing)}",
            blocking=True,
        )
    return _check(
        check_id="scope",
        label="任务参数",
        status="ok",
        message="必填参数齐全",
    )


def _resolve_agent_strategy(request: ExternalTaskCreateRequest) -> str:
    raw = str(request.agent_strategy or "").strip()
    if raw:
        return raw
    return default_strategy_for_platform(str(request.platform or "douyin")).id


async def _build_brief_from_request(
    request: ExternalTaskCreateRequest,
    *,
    message: str,
    config: dict[str, Any],
    settings: Settings,
    tenant_id: str,
    provider: str,
) -> TaskBrief:
    from app.services.external_task_service import enrich_brief_from_external_config

    brief = TaskBrief(
        brief_md=message,
        platform=str(request.platform or "douyin"),
        title=request.name,
        agent_strategy=_resolve_agent_strategy(request),
    )
    brief, _meta = await update_task_config(
        brief,
        config=config,
        settings=settings,
        tenant_id=tenant_id,
        provider=provider,
    )
    brief = enrich_brief_from_external_config(brief, config)
    strategy = resolve_agent_strategy(brief.agent_strategy, platform=brief.platform or request.platform)
    brief.goals["execution_mode"] = strategy.execution_mode
    brief.agent_strategy = strategy.id
    return brief


def _collect_missing_skills(
    *,
    tenant_id: str,
    platform: str,
    strategy_id: str,
    step_actions: list[str],
    settings: Settings,
) -> list[str]:
    store = SkillStore(settings)
    store._ensure_global_defaults()
    enabled_ids = {s.id for s in store.list_enabled(tenant_id)}
    missing: list[str] = []
    standalone = strategy_id == "standalone-browse-douyin"
    for action in step_actions:
        if action in INTERNAL_SUPERVISOR_ACTIONS:
            continue
        if standalone and action in CRAWL_SUPERVISOR_ACTIONS:
            continue
        skill_id = skill_id_for_supervisor_action(action, platform, strategy_id=strategy_id)
        if not skill_id:
            missing.append(f"{action}(未绑定 Skill)")
            continue
        resolved = resolve_skill_id(skill_id)
        if resolved not in enabled_ids:
            missing.append(resolved)
    return missing


def _orchestration_check(
    *,
    brief: TaskBrief,
    config: dict[str, Any],
    tenant_id: str,
    settings: Settings,
    intent: str,
) -> tuple[ExternalTaskPreflightCheck, ExternalTaskPreflightOrchestrationPreview]:
    plan = build_supervisor_execution_plan(brief, {})
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    step_rows = [
        {
            "order": row.get("order"),
            "action": row.get("action"),
            "label": row.get("label") or row.get("action"),
        }
        for row in steps
        if isinstance(row, dict)
    ]
    actions = [str(row.get("action") or "") for row in steps if isinstance(row, dict)]
    strategy_id = str(brief.agent_strategy or _resolve_agent_strategy_from_brief(brief))
    preview = ExternalTaskPreflightOrchestrationPreview(
        summary=str(plan.get("summary") or ""),
        steps=step_rows,
        agent_strategy=strategy_id,
        execution_mode=str(brief.goals.get("execution_mode") or ""),
    )

    missing_skills = _collect_missing_skills(
        tenant_id=tenant_id,
        platform=str(brief.platform or "douyin"),
        strategy_id=strategy_id,
        step_actions=actions,
        settings=settings,
    )
    if missing_skills:
        return (
            _check(
                check_id="skills",
                label="执行工具",
                status="error",
                message=f"缺少或未启用 Skill：{', '.join(missing_skills[:5])}",
                blocking=True,
            ),
            preview,
        )

    wants_evaluation = bool(config.get("evaluation"))
    has_evaluate_step = "evaluate_leads" in actions
    standalone_flow = is_standalone_browse_brief(brief) or plan.get("pipeline") == STANDALONE_PIPELINE
    keyword_flow = intent == "keyword_auto" and "crawl_keyword" in actions
    manual_flow = intent in {"single_video", "account_home"} and any(
        action in actions for action in ("crawl_content_url", "crawl_profile")
    )
    if not standalone_flow and (keyword_flow or manual_flow) and not has_evaluate_step:
        return (
            _check(
                check_id="orchestration",
                label="任务编排",
                status="error",
                message="编排计划缺少「LLM 评估」步骤，创建后将无法产出精准客户",
                blocking=True,
            ),
            preview,
        )
    if wants_evaluation and not has_evaluate_step and not standalone_flow:
        return (
            _check(
                check_id="orchestration",
                label="任务编排",
                status="warning",
                message="当前编排未包含 LLM 评估步骤，已配置的评估规则可能不会生效",
            ),
            preview,
        )
    if not actions:
        return (
            _check(
                check_id="orchestration",
                label="任务编排",
                status="error",
                message="无法生成执行计划，请检查任务类型与参数",
                blocking=True,
            ),
            preview,
        )
    return (
        _check(
            check_id="orchestration",
            label="任务编排",
            status="ok",
            message=f"已生成 {len(step_rows)} 步执行计划"
            + ("，含 LLM 评估" if has_evaluate_step else ""),
        ),
        preview,
    )


def _resolve_agent_strategy_from_brief(brief: TaskBrief) -> str:
    if brief.agent_strategy:
        return str(brief.agent_strategy)
    return default_strategy_for_platform(str(brief.platform or "douyin")).id


async def run_external_task_preflight(
    request: ExternalTaskCreateRequest,
    *,
    settings: Settings,
    tenant_id: str,
    account_id: str,
) -> ExternalTaskPreflightOut:
    checks: list[ExternalTaskPreflightCheck] = []

    scope_check = _validate_scope(request)
    if scope_check is not None:
        checks.append(scope_check)
        if scope_check.status == "error":
            return _finalize(checks)

    try:
        message, config, _correlation = normalize_external_create(request)
    except ValueError as exc:
        checks.append(
            _check(
                check_id="normalize",
                label="任务参数",
                status="error",
                message=str(exc) or "参数归一化失败",
                blocking=True,
            )
        )
        return _finalize(checks)

    checks.append(
        _check(
            check_id="runtime",
            label="智能体运行时",
            status="ok",
            message="Sidecar 已响应，可接收任务",
        )
    )

    platform = str(request.platform or "douyin").strip().lower()
    login_status: dict[str, Any] = {}
    cookie_ready = False
    login_error: Exception | None = None
    try:
        store = get_session_store(settings, platform)
        login_status = store.login_status(tenant_id, account_id)
        cookie_ready = _is_platform_cookie_ready(login_status)
    except Exception as exc:
        login_error = exc

    if login_error is not None:
        checks.append(
            _check(
                check_id="login",
                label="平台登录",
                status="error",
                message=f"无法读取登录态：{login_error}",
                blocking=True,
            )
        )
    elif cookie_ready:
        nickname = str(
            login_status.get("nickname")
            or login_status.get("display_name")
            or login_status.get("username")
            or ""
        ).strip()
        checks.append(
            _check(
                check_id="login",
                label="平台登录",
                status="ok",
                message=f"{platform} 登录态可用" + (f"（{nickname}）" if nickname else ""),
            )
        )
    else:
        msg = str(login_status.get("message") or login_status.get("status") or "未登录或 Cookie 失效")
        checks.append(
            _check(
                check_id="login",
                label="平台登录",
                status="error",
                message=f"{platform} 未就绪：{msg}。请先在账号设置完成浏览器绑定",
                blocking=True,
            )
        )

    provider = resolve_default_provider(settings)
    factory = AIClientFactory(settings)
    llm_configured = factory.llm_configured()
    if llm_configured:
        checks.append(
            _check(
                check_id="llm",
                label="LLM 服务",
                status="ok",
                message="已配置 DeepSeek，可用于编排决策与线索评估",
            )
        )
    else:
        checks.append(
            _check(
                check_id="llm",
                label="LLM 服务",
                status="error",
                message="未配置 DeepSeek API Key，智能体无法评估评论、无法产出精准客户",
                blocking=True,
            )
        )

    brief = await _build_brief_from_request(
        request,
        message=message,
        config=config,
        settings=settings,
        tenant_id=tenant_id,
        provider=provider,
    )
    orch_check, orchestration = _orchestration_check(
        brief=brief,
        config=config,
        tenant_id=tenant_id,
        settings=settings,
        intent=resolve_intent(intent=request.intent),
    )
    checks.append(orch_check)

    eval_draft = evaluation_draft_from_payload(config.get("evaluation"))
    rule_spec = build_rule_based_spec(brief, draft=eval_draft or None)
    accept_preview = evaluation_preview_text(rule_spec).strip()
    evaluation = ExternalTaskPreflightEvaluationPreview(
        ready=bool(llm_configured or accept_preview),
        provider=str(provider or ""),
        llm_configured=llm_configured,
        accept_preview=accept_preview[:160],
    )
    if llm_configured or accept_preview:
        checks.append(
            _check(
                check_id="evaluation",
                label="线索评估",
                status="ok" if llm_configured else "warning",
                message="大模型将根据获客主题自动识别评论意向"
                if llm_configured
                else "评估规则已就绪（建议配置 LLM 以获得更好效果）",
            )
        )
    else:
        checks.append(
            _check(
                check_id="evaluation",
                label="线索评估",
                status="warning",
                message="未配置有效线索评估规则，任务只能抓取评论，无法筛选精准客户",
            )
        )

    constraints = config.get("constraints") if isinstance(config.get("constraints"), dict) else {}
    has_reply = bool(
        constraints.get("comment_preset_ids")
        or constraints.get("reply_template")
        or constraints.get("reply_templates")
        or config.get("reply_templates")
        or config.get("reply_template")
    )
    has_dm = bool(
        constraints.get("dm_preset_ids")
        or constraints.get("dm_template")
        or constraints.get("dm_templates")
        or config.get("dm_templates")
        or config.get("dm_template")
    )
    outreach_actions = [a for a in orchestration.steps if str(a.get("action") or "") in {"reply", "dm", "follow"}]
    if outreach_actions and not has_reply and not has_dm:
        checks.append(
            _check(
                check_id="outreach_templates",
                label="触达模板",
                status="warning",
                message="编排含触达步骤，但未选择评论/私信模板，触达可能跳过或使用空文案",
            )
        )

    return _finalize(checks, orchestration=orchestration, evaluation=evaluation)


def _finalize(
    checks: list[ExternalTaskPreflightCheck],
    *,
    orchestration: ExternalTaskPreflightOrchestrationPreview | None = None,
    evaluation: ExternalTaskPreflightEvaluationPreview | None = None,
) -> ExternalTaskPreflightOut:
    blocking_count = sum(1 for item in checks if item.blocking)
    warning_count = sum(1 for item in checks if item.status == "warning")
    ready = blocking_count == 0
    return ExternalTaskPreflightOut(
        ready=ready,
        blocking_count=blocking_count,
        warning_count=warning_count,
        checks=checks,
        orchestration=orchestration,
        evaluation=evaluation,
    )
