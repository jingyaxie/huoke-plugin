"""Supervisor 抓取/触达参数合并与重试辅助（skill_flow 计划驱动）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.supervisor_outreach import outreach_quotas_exhausted, pick_outreach_target_params
from app.services.task_brief_service import TaskBrief, is_skill_flow_brief

OUTREACH_LOOP_ACTIONS = frozenset({"reply", "dm", "follow"})
PLAN_RESET_ACTIONS = frozenset(
    {"crawl_keyword", "crawl_content_url", "crawl_profile", "query_stats", "outreach", "reply", "dm", "follow"}
)
CRAWL_SUPERVISOR_ACTIONS = frozenset({"crawl_keyword", "crawl_content_url", "crawl_profile"})
DEFAULT_CRAWL_VIDEO_LIMIT = 5
CRAWL_VIDEO_LIMIT_KEYS = ("crawl_video_limit", "video_limit", "content_limit", "limit", "video_limit_per_batch")


def _positive_int(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def video_publish_days_from(
    brief: TaskBrief | None = None,
    params: dict[str, Any] | None = None,
) -> int | None:
    """视频搜索/发布时间筛选天数（抖音精选「发布时间」筛选项）。"""
    src = params or {}
    val = src.get("video_publish_days")
    if val is None and brief is not None:
        val = brief.goals.get("video_publish_days")
    return _positive_int(val)


def comment_capture_days_from(
    brief: TaskBrief | None = None,
    params: dict[str, Any] | None = None,
) -> int | None:
    """评论入库时间窗（与视频发布时间筛选独立，表单两项分别生效）。"""
    src = params or {}
    val = src.get("comment_days")
    if val is None and brief is not None:
        val = brief.goals.get("comment_days")
    if val is None:
        val = src.get("days")
    return _positive_int(val)


def build_crawl_day_params(
    brief: TaskBrief,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """拆分 video_publish_days（搜视频）与 comment_days（筛评论），避免 days 混用。"""
    out: dict[str, Any] = {}
    publish = video_publish_days_from(brief, params)
    comment = comment_capture_days_from(brief, params)
    if publish is not None:
        out["video_publish_days"] = publish
    if comment is not None:
        out["comment_days"] = comment
    return out


@dataclass(frozen=True)
class CrawlEvaluateGate:
    """抓取阶段门禁：防止只抓不评无限循环。"""

    force_evaluate: bool = False
    suspend: bool = False
    reason: str = ""
    completion_outcome: str | None = None


def effective_comments_inventory(state: dict[str, Any]) -> int:
    """已入库/已抓取评论规模（用于门禁，取 state 中较大值）。"""
    captured = int(state.get("comments_captured") or 0)
    persisted = int(state.get("comments_persisted") or 0)
    return max(captured, persisted)


def crawl_rounds_without_evaluation(state: dict[str, Any]) -> int:
    return int(state.get("crawl_rounds_without_eval") or 0)


def crawl_evaluate_thresholds(brief: TaskBrief) -> dict[str, int]:
    """阈值可由 brief.goals 覆盖；默认与目标线索数、每批视频数挂钩。"""
    target = max(1, int(brief.goals.get("target_leads") or 5))
    video_limit = effective_crawl_video_limit(brief)

    min_comments = int(brief.goals.get("min_comments_before_evaluate") or 0)
    if min_comments <= 0:
        min_comments = max(30, target * 10, video_limit * 15)

    max_rounds = int(brief.goals.get("max_crawl_rounds_before_evaluate") or 3)
    if max_rounds <= 0:
        max_rounds = 3

    hard_cap = int(brief.goals.get("max_comments_captured") or 0)
    if hard_cap <= 0:
        hard_cap = max(500, min_comments * 5, 2500)

    return {
        "min_comments_before_evaluate": min_comments,
        "max_crawl_rounds_before_evaluate": max_rounds,
        "max_comments_hard_cap": hard_cap,
    }


def crawl_evaluate_gate(brief: TaskBrief, state: dict[str, Any]) -> CrawlEvaluateGate:
    """评估未完成时，判断应强制评估或挂起停止抓取。"""
    if not is_skill_flow_brief(brief):
        return CrawlEvaluateGate()
    if state.get("evaluation_done"):
        return CrawlEvaluateGate()

    thresholds = crawl_evaluate_thresholds(brief)
    inventory = effective_comments_inventory(state)
    rounds = crawl_rounds_without_evaluation(state)
    min_comments = thresholds["min_comments_before_evaluate"]
    max_rounds = thresholds["max_crawl_rounds_before_evaluate"]
    hard_cap = thresholds["max_comments_hard_cap"]

    if inventory >= hard_cap:
        return CrawlEvaluateGate(
            suspend=True,
            reason=(
                f"已入库评论 {inventory} 条，达到上限 {hard_cap}；"
                "任务已暂停，请「继续执行」触发 LLM 评估，或调整关键词/评估标准"
            ),
            completion_outcome="crawl_inventory_cap",
        )

    if inventory >= min_comments:
        return CrawlEvaluateGate(
            force_evaluate=True,
            reason=f"已抓取 {inventory} 条评论（≥{min_comments}），停止继续抓取，进入 LLM 评估",
        )

    if rounds >= max_rounds and inventory > 0:
        return CrawlEvaluateGate(
            force_evaluate=True,
            reason=f"已连续抓取 {rounds} 轮（≥{max_rounds}）未评估，强制进入 LLM 评估",
        )

    if rounds >= max_rounds and inventory <= 0:
        return CrawlEvaluateGate(
            suspend=True,
            reason=f"已连续抓取 {rounds} 轮仍未入库评论，任务暂停；请检查登录态或更换关键词",
            completion_outcome="crawl_no_inventory",
        )

    if state.get("crawl_search_exhausted") and inventory > 0:
        return CrawlEvaluateGate(
            force_evaluate=True,
            reason=f"搜索列表已扫完，已入库 {inventory} 条评论，进入 LLM 评估",
        )

    return CrawlEvaluateGate()


def record_crawl_round_without_evaluation(state: dict[str, Any]) -> None:
    if state.get("evaluation_done"):
        return
    state["crawl_rounds_without_eval"] = crawl_rounds_without_evaluation(state) + 1


def reset_crawl_evaluate_gate_state(state: dict[str, Any]) -> None:
    state.pop("crawl_rounds_without_eval", None)
    state.pop("crawl_evaluate_gate_reason", None)


def _normalize_job_id(job_id: str | None) -> str:
    return str(job_id or "").strip()


def _task_watched_content_ids(state: dict[str, Any] | None, job_id: str) -> list[str]:
    if not isinstance(state, dict):
        return []
    stored_job = _normalize_job_id(state.get("job_id"))
    if stored_job and job_id and stored_job != job_id:
        return []
    return list(state.get("watched_content_ids") or [])


def _task_supervisor_slice(state: dict[str, Any] | None, job_id: str) -> dict[str, Any]:
    watched = _task_watched_content_ids(state, job_id)
    if job_id:
        return {"job_id": job_id, "watched_content_ids": watched}
    return {"watched_content_ids": watched}


def show_browser(brief: TaskBrief) -> bool:
    if brief.goals.get("show_browser") is True:
        return True
    if brief.goals.get("headless") is False:
        return True
    return bool(brief.goals.get("show_browser", False))


def browser_headless(brief: TaskBrief) -> bool:
    if brief.goals.get("headless") is True:
        return True
    if brief.goals.get("headless") is False:
        return False
    return not show_browser(brief)


def merge_skill_flow_crawl_params(
    merged: dict[str, Any],
    *,
    brief: TaskBrief,
    state: dict[str, Any] | None = None,
    job_id: str | None = None,
) -> None:
    """类人分步抓取：搜索必须通过搜索框输入关键词，禁止 JS 直调与拼接搜索 URL。"""
    merged["ui_search_only"] = True
    merged["search_url_first"] = False
    merged.setdefault("show_browser", show_browser(brief))
    merged.setdefault("force_refresh", True)
    merged.setdefault("include_full_results", True)
    if brief.goals.get("ui_first"):
        merged["ui_first"] = True
        merged.setdefault("capture_mode", "ui_passive")
    jid = _normalize_job_id(job_id or merged.get("job_id") or (state or {}).get("job_id"))
    if jid:
        merged["job_id"] = jid
    watched = _task_watched_content_ids(state, jid)
    if watched:
        merged["watched_content_ids"] = watched
    merged["supervisor_state"] = _task_supervisor_slice(state, jid)
    platform_options = merged.get("platform_options")
    if not isinstance(platform_options, dict):
        platform_options = {}
    platform_options.setdefault("entry", "jingxuan")
    merged["platform_options"] = platform_options


def merge_outreach_params(
    merged: dict[str, Any],
    *,
    brief: TaskBrief,
    action: str,
    db_session: Session | None,
    settings: Settings,
    tenant_id: str,
    platform: str,
    account_id: str,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """从已入库数据填充触达参数；失败时返回 error dict。"""
    if db_session is None:
        return {"error": "触达需要数据库会话，无法从已入库评论选线索", "status": "failed"}
    target_params = pick_outreach_target_params(
        db_session,
        settings,
        tenant_id=tenant_id,
        platform=platform,
        account_id=account_id,
        brief=brief,
        state=state or {},
        action=action,
    )
    if not target_params:
        label = {"reply": "触达线索", "dm": "私信用户", "follow": "关注用户"}.get(action, action)
        return {"error": f"已入库评论中无匹配待{label}", "status": "failed"}
    merged.update(target_params)
    merged.setdefault("prefer_human_ui", bool(brief.goals.get("ui_first", False)))
    merged.setdefault("prefer_ui_reply", bool(brief.goals.get("ui_first", False)))
    merged.setdefault("ui_first", bool(brief.goals.get("ui_first", False)))
    if action in {"dm", "follow"}:
        merged.setdefault("show_browser", show_browser(brief))
    return None


def should_resume_crawl_on_no_match(
    brief: TaskBrief,
    state: dict[str, Any],
    stats: dict[str, Any] | None = None,
) -> bool:
    if not is_skill_flow_brief(brief):
        return False
    # 手动获客（主页/单视频）一轮抓取后不应因「0 精准线索」回退重抓同一链接
    mode = str(brief.goals.get("acquisition_mode") or "").strip().lower()
    if mode in {"account_home", "single_video"}:
        return False
    gate = crawl_evaluate_gate(brief, state)
    if gate.force_evaluate or gate.suspend:
        return False
    if state.get("crawl_search_exhausted"):
        return False
    leads = int(state.get("leads_collected") or 0)
    target = int(brief.goals.get("target_leads") or 0)
    if target > 0 and leads >= target:
        return False
    if stats and outreach_quotas_exhausted(stats, brief):
        return False
    return True


def prepare_crawl_retry(state: dict[str, Any]) -> None:
    state.pop("crawl_done", None)
    state.pop("visible_crawl_done", None)
    state.pop("stats_synced", None)
    state.pop("last_stats", None)
    state.pop("last_crawl_error", None)
    state.pop("crawl_search_exhausted", None)
    for key in ("comments_captured", "raw_comments_scanned", "comments_persisted"):
        state.pop(key, None)


def reset_plan_evaluation_state(state: dict[str, Any], plan: dict[str, Any] | None) -> None:
    """重抓或手动继续时清除评估标记，避免 evaluate 步被计划驱动逻辑跳过。"""
    state.pop("evaluation_done", None)
    state.pop("leads_qualified", None)
    state.pop("comments_evaluated", None)
    state.pop("crawl_evaluate_gate_reason", None)
    if not isinstance(plan, dict):
        return
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("action") or "") == "evaluate_leads":
            step["status"] = "pending"


def prepare_plan_recrawl(
    state: dict[str, Any],
    plan: dict[str, Any] | None,
    *,
    brief: TaskBrief,
) -> None:
    """类人分步重抓：清除 crawl_done 并将计划回退到 crawl/sync 步。"""
    if not is_skill_flow_brief(brief):
        return
    prepare_crawl_retry(state)
    state["watched_content_ids"] = []
    state.pop("url_revisited_content_ids", None)
    if not isinstance(plan, dict):
        return
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "")
        if action in CRAWL_SUPERVISOR_ACTIONS or action == "query_stats":
            step["status"] = "pending"
        elif action in OUTREACH_LOOP_ACTIONS:
            step["status"] = "pending"
        elif action == "complete":
            step["status"] = "pending"
        elif action == "evaluate_leads":
            step["status"] = "pending"
    reset_plan_evaluation_state(state, plan)
    plan["current_index"] = 0
    state["execution_plan"] = plan


def explicit_crawl_video_limit(
    brief: TaskBrief | None = None,
    params: dict[str, Any] | None = None,
) -> int | None:
    for src in (params or {}, (brief.goals if brief else {}) or {}):
        if not isinstance(src, dict):
            continue
        for key in CRAWL_VIDEO_LIMIT_KEYS:
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


def effective_crawl_video_limit(
    brief: TaskBrief | None = None,
    params: dict[str, Any] | None = None,
    *,
    default: int = DEFAULT_CRAWL_VIDEO_LIMIT,
) -> int:
    return explicit_crawl_video_limit(brief=brief, params=params) or default


def apply_crawl_video_limit_aliases(params: dict[str, Any], video_limit: int) -> None:
    params["crawl_video_limit"] = video_limit
    params.setdefault("video_limit", video_limit)
    params.setdefault("content_limit", video_limit)
    params.setdefault("limit", video_limit)


def crawl_step_params(brief: TaskBrief, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "keyword": brief.keyword or "",
        "region": brief.region,
        **build_crawl_day_params(brief),
    }
    apply_crawl_video_limit_aliases(params, effective_crawl_video_limit(brief=brief))
    if extra:
        params.update(extra)
    return params


def build_crawl_keyword_params(brief: TaskBrief) -> dict[str, Any]:
    params = crawl_step_params(brief)
    apply_crawl_video_limit_aliases(params, effective_crawl_video_limit(brief=brief, params=params))
    if is_skill_flow_brief(brief):
        merge_skill_flow_crawl_params(params, brief=brief)
    return params


def build_crawl_content_url_params(brief: TaskBrief) -> dict[str, Any]:
    url = str(brief.goals.get("video_url") or brief.goals.get("input_url") or "").strip()
    return {
        "video_url": url,
        "note_url": url,
        **build_crawl_day_params(brief),
        "show_browser": show_browser(brief),
    }


def build_crawl_profile_params(brief: TaskBrief) -> dict[str, Any]:
    url = str(brief.goals.get("profile_url") or brief.goals.get("input_url") or "").strip()
    params: dict[str, Any] = {
        "profile_url": url,
        **build_crawl_day_params(brief),
        "show_browser": show_browser(brief),
    }
    apply_crawl_video_limit_aliases(params, effective_crawl_video_limit(brief=brief))
    return params


def build_crawl_action_params(brief: TaskBrief, action: str) -> dict[str, Any]:
    if action == "crawl_content_url":
        return build_crawl_content_url_params(brief)
    if action == "crawl_profile":
        return build_crawl_profile_params(brief)
    return build_crawl_keyword_params(brief)


def infer_suspend_next_action(
    reason: str,
    state: dict[str, Any],
    brief: TaskBrief,
    *,
    resume_next: bool,
    crawl_done: bool,
) -> str:
    if "配额" in reason:
        if resume_next:
            return "自动恢复后：同步今日 reply/follow/dm 配额 → 从已入库评论继续独立触达"
        return "手动「继续执行」：同步配额后继续 reply / dm / follow"

    if any(token in reason for token in ("无匹配", "已入库评论", "待触达线索", "扫完")):
        if state.get("crawl_search_exhausted"):
            return "已扫完搜索列表仍无匹配：请调整线索评估标准或更换搜索词后「继续执行」"
        if resume_next:
            return "自动恢复后会继续浏览更多视频并匹配；也可现在「继续执行」立即重试"
        return "点击「继续执行」继续浏览更多视频并匹配评论"

    if crawl_done:
        return "继续执行：同步配额 → 从已入库评论按 plan 独立 reply / dm / follow"

    return "点击「继续执行」继续抓取关键词相关视频评论"


def _normalize_content_id(raw: Any) -> str:
    return str(raw or "").strip()


def url_revisited_content_ids(state: dict[str, Any]) -> set[str]:
    return {
        _normalize_content_id(x)
        for x in (state.get("url_revisited_content_ids") or [])
        if _normalize_content_id(x)
    }


def pending_url_revisit_content_ids(state: dict[str, Any]) -> list[str]:
    watched = [
        _normalize_content_id(x)
        for x in (state.get("watched_content_ids") or [])
        if _normalize_content_id(x)
    ]
    revisited = url_revisited_content_ids(state)
    return [cid for cid in watched if cid not in revisited]


def content_id_to_video_url(platform: str, content_id: str) -> str:
    cid = _normalize_content_id(content_id)
    if not cid:
        return ""
    plat = str(platform or "douyin").strip().lower()
    if plat == "douyin":
        return f"https://www.douyin.com/video/{cid}"
    if plat == "xiaohongshu":
        return f"https://www.xiaohongshu.com/explore/{cid}"
    return ""


def pick_next_url_revisit_target(brief: TaskBrief, state: dict[str, Any]) -> dict[str, str] | None:
    """skill_flow：已有 watched 视频但评论未入库时，优先直开 URL 补抓，避免重复走搜索框。"""
    if not is_skill_flow_brief(brief):
        return None
    if state.get("crawl_done"):
        return None
    pending = pending_url_revisit_content_ids(state)
    if not pending:
        return None
    platform = str(brief.platform or "douyin").strip().lower()
    content_id = pending[0]
    video_url = content_id_to_video_url(platform, content_id)
    if not video_url:
        return None
    return {"content_id": content_id, "video_url": video_url}


def mark_url_revisited(state: dict[str, Any], content_id: str) -> None:
    cid = _normalize_content_id(content_id)
    if not cid:
        return
    existing = url_revisited_content_ids(state)
    existing.add(cid)
    state["url_revisited_content_ids"] = sorted(existing)


def build_url_revisit_decision(
    brief: TaskBrief,
    state: dict[str, Any],
    *,
    reasoning: str,
    plan_step_id: str = "crawl",
) -> dict[str, Any] | None:
    target = pick_next_url_revisit_target(brief, state)
    if not target:
        return None
    content_id = target["content_id"]
    video_url = target["video_url"]
    return {
        "action": "crawl_content_url",
        "reasoning": reasoning,
        "params": {
            "video_url": video_url,
            "note_url": video_url,
            "keyword": brief.keyword,
            **build_crawl_day_params(brief),
            "region": brief.region,
            "show_browser": show_browser(brief),
            "ui_passive": True,
            "capture_mode": "video_url_ui_passive",
            "_revisit_content_id": content_id,
            "_revisit_under_crawl_step": True,
        },
        "goal_progress": {
            "leads_collected": int(state.get("leads_collected") or 0),
            "comments_captured": int(state.get("comments_captured") or 0),
            "target_leads": int(brief.goals.get("target_leads") or 0),
        },
        "plan_step_id": plan_step_id,
    }


def maybe_prefer_url_revisit_decision(
    brief: TaskBrief,
    state: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    if str(decision.get("action") or "") != "crawl_keyword":
        return decision
    revisit = build_url_revisit_decision(
        brief,
        state,
        reasoning=str(decision.get("reasoning") or "【补抓】直接打开已发现视频补抓评论（跳过搜索框）"),
        plan_step_id=str(decision.get("plan_step_id") or "crawl"),
    )
    return revisit if revisit is not None else decision


def count_crawl_from_skill_result(skill_result: dict[str, Any]) -> int:
    from app.services.supervisor_outreach import count_crawl_comments

    structured = count_crawl_comments(skill_result)
    if structured:
        return structured
    for key in ("total_comments_captured", "total_comments"):
        val = skill_result.get(key)
        if val:
            return int(val)
    inner = skill_result.get("result")
    if isinstance(inner, dict):
        for key in ("total_comments_captured", "total_comments", "collected_count"):
            val = inner.get(key)
            if val:
                return int(val)
    results = skill_result.get("results") or []
    if isinstance(results, list):
        total = sum(
            int(row.get("total_comments_captured") or row.get("comment_count") or 0)
            for row in results
            if isinstance(row, dict)
        )
        if total:
            return total
    return 0
