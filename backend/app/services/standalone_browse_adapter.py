"""抖音 standalone 浏览 ↔ Supervisor 适配层。

与 skill-flow-douyin 并行：仅当 brief.agent_strategy == standalone-browse-douyin
（或 goals.use_standalone_browse=true）时走本模块；否则 Supervisor 仍走原 Skill 链路。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.platforms.douyin.standalone_keyword_browse import (
    PreciseLeadRecord,
    StandaloneKeywordBrowseResult,
    build_standalone_browse_config,
    capture_method_for_mode,
    run_standalone_keyword_browse_with_browser,
)
from app.services.manual_acquisition_service import manual_acquisition_mode
from app.services.supervisor_crawl_helpers import (
    apply_crawl_video_limit_aliases,
    build_crawl_day_params,
    effective_crawl_video_limit,
    explicit_crawl_video_limit,
    show_browser,
)

STANDALONE_KEYWORD_MAX_VIDEOS_DEFAULT = 200
STANDALONE_PLAN_VERSION = 4
from app.services.supervisor_outreach import (
    build_dm_text,
    build_reply_text,
    outreach_interval_from_brief,
)
from app.services.task_brief_service import TaskBrief

STANDALONE_BROWSE_STRATEGY_ID = "standalone-browse-douyin"
STANDALONE_PIPELINE = "standalone_browse"


def is_standalone_browse_brief(brief: TaskBrief) -> bool:
    """是否走 standalone 一体化浏览（抖音专用）。"""
    if str(brief.platform or "douyin").strip().lower() != "douyin":
        return False
    strategy = str(brief.agent_strategy or brief.goals.get("agent_strategy") or "").strip()
    if strategy == STANDALONE_BROWSE_STRATEGY_ID:
        return True
    return bool(brief.goals.get("use_standalone_browse"))


def _match_keywords_from_brief(brief: TaskBrief) -> list[str]:
    for src in (brief.constraints, brief.goals):
        if not isinstance(src, dict):
            continue
        raw = src.get("match_keywords")
        if isinstance(raw, list) and raw:
            return [str(x).strip() for x in raw if str(x).strip()]
    keyword = str(brief.keyword or "").strip()
    return [keyword] if keyword else []


def _reject_keywords_from_brief(brief: TaskBrief) -> list[str]:
    spec = brief.constraints.get("lead_evaluation")
    if isinstance(spec, dict):
        reject = spec.get("reject_signals")
        if isinstance(reject, list) and reject:
            return [str(x).strip() for x in reject if str(x).strip()]
        reject_desc = str(spec.get("reject_description") or "").strip()
        if reject_desc:
            return [reject_desc]
    return _exclude_keywords_from_brief(brief)


def _reply_dm_templates_from_brief(brief: TaskBrief) -> tuple[str, str]:
    reply = ""
    dm = ""
    templates = brief.constraints.get("reply_templates")
    if isinstance(templates, list) and templates:
        reply = str(templates[0] or "").strip()
    dm_templates = brief.constraints.get("dm_templates")
    if isinstance(dm_templates, list) and dm_templates:
        dm = str(dm_templates[0] or "").strip()
    if not reply:
        reply = build_reply_text(brief, nickname="朋友", comment="咨询")
    if not dm:
        dm = build_dm_text(brief, nickname="朋友", comment="咨询")
    return reply, dm


def _llm_eval_from_brief(brief: TaskBrief) -> tuple[bool, dict[str, Any] | None]:
    spec = brief.constraints.get("lead_evaluation")
    if isinstance(spec, dict) and str(spec.get("schema") or "") == "huoke.lead_evaluation.v1":
        return True, dict(spec)
    return False, None


def _standalone_max_videos_cap(
    brief: TaskBrief,
    params: dict[str, Any],
    *,
    target_leads: int,
    action: str,
) -> int:
    """单步浏览视频上限（安全阀），与 target_leads（精准线索目标）分离。"""
    manual = manual_acquisition_mode(brief)
    if manual == "account_home" or action == "crawl_profile":
        return effective_crawl_video_limit(brief=brief, params=params)
    explicit = explicit_crawl_video_limit(brief=brief, params=params)
    if explicit is not None and explicit != target_leads:
        return explicit
    for key in ("max_videos_to_browse", "max_videos_per_batch"):
        for src in (params, brief.goals):
            if not isinstance(src, dict):
                continue
            val = src.get(key)
            if val is None:
                continue
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            if n > 0:
                return n
    return STANDALONE_KEYWORD_MAX_VIDEOS_DEFAULT


def _target_leads_from_brief(brief: TaskBrief, params: dict[str, Any], *, action: str) -> int:
    for key in ("target_leads", "target_count", "target_precise_leads"):
        for src in (brief.goals, params):
            val = src.get(key) if isinstance(src, dict) else None
            if val is not None and str(val).strip() != "":
                try:
                    return max(1, int(val))
                except (TypeError, ValueError):
                    continue
    manual = manual_acquisition_mode(brief)
    if manual == "single_video" or action == "crawl_content_url":
        return 5
    if manual == "account_home" or action == "crawl_profile":
        limit = brief.goals.get("crawl_video_limit") or params.get("crawl_video_limit")
        if limit is not None:
            try:
                return max(1, int(limit))
            except (TypeError, ValueError):
                pass
    return max(1, int(brief.goals.get("target_leads") or 3))


def _exclude_keywords_from_brief(brief: TaskBrief) -> list[str]:
    for src in (brief.constraints, brief.goals):
        if not isinstance(src, dict):
            continue
        raw = src.get("exclude_keywords")
        if isinstance(raw, list) and raw:
            return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _action_ratios_from_brief(brief: TaskBrief) -> tuple[int, int, int]:
    pct = brief.constraints.get("comment_dm_percentage")
    try:
        dm_pct = int(pct) if pct is not None else 30
    except (TypeError, ValueError):
        dm_pct = 30
    dm_pct = max(0, min(100, dm_pct))
    comment_pct = max(0, 100 - dm_pct)
    follow_pct = max(0, min(20, 100 - comment_pct - dm_pct))
    if comment_pct + dm_pct + follow_pct == 0:
        return 50, 30, 20
    return comment_pct, dm_pct, follow_pct or 20


def _acquisition_mode_for_action(action: str, brief: TaskBrief) -> str:
    manual = manual_acquisition_mode(brief)
    if manual == "single_video":
        return "single_video"
    if manual == "account_home":
        return "account_home"
    if action == "crawl_content_url":
        return "single_video"
    if action == "crawl_profile":
        return "account_home"
    return "keyword_auto"


def _comment_browse_limits_from_brief(
    brief: TaskBrief,
    params: dict[str, Any],
    *,
    target: int,
) -> tuple[int, int]:
    """单视频评论翻页上限：优先表单/params，否则按目标线索数放大默认值。"""
    comments_cap: int | None = None
    scroll_rounds: int | None = None
    for key in ("max_comments_per_video", "max_comments", "comment_limit"):
        for src in (params, brief.goals, brief.constraints):
            if not isinstance(src, dict):
                continue
            val = src.get(key)
            if val is not None and str(val).strip() != "":
                try:
                    comments_cap = max(50, int(val))
                    break
                except (TypeError, ValueError):
                    continue
        if comments_cap is not None:
            break
    for key in ("comment_scroll_rounds", "max_comment_scroll_rounds"):
        for src in (params, brief.goals, brief.constraints):
            if not isinstance(src, dict):
                continue
            val = src.get(key)
            if val is not None and str(val).strip() != "":
                try:
                    scroll_rounds = max(24, int(val))
                    break
                except (TypeError, ValueError):
                    continue
        if scroll_rounds is not None:
            break
    if comments_cap is None:
        comments_cap = max(300, int(target) * 40)
    if scroll_rounds is None:
        scroll_rounds = max(60, comments_cap // 5)
    return comments_cap, scroll_rounds


def brief_to_standalone_config(
    brief: TaskBrief,
    params: dict[str, Any],
    *,
    action: str,
) -> Any:
    """TaskBrief + Supervisor params → StandaloneKeywordBrowseConfig。"""
    mode = _acquisition_mode_for_action(action, brief)
    day_params = build_crawl_day_params(brief, params)
    target = _target_leads_from_brief(brief, params, action=action)
    video_limit = _standalone_max_videos_cap(
        brief, params, target_leads=target, action=action,
    )
    comment_ratio, dm_ratio, follow_ratio = _action_ratios_from_brief(brief)
    validate_only = bool(brief.goals.get("outreach_validate_only"))
    reply_text, dm_text = _reply_dm_templates_from_brief(brief)
    publish_days = day_params.get("video_publish_days")
    comment_days = day_params.get("comment_days")
    days = int(publish_days if publish_days is not None else comment_days if comment_days is not None else brief.goals.get("comment_days") or 7)

    video_url = str(
        params.get("video_url")
        or brief.goals.get("video_url")
        or brief.goals.get("input_url")
        or ""
    ).strip()
    profile_url = str(
        params.get("profile_url")
        or brief.goals.get("profile_url")
        or brief.goals.get("input_url")
        or ""
    ).strip()
    region = str(brief.region or params.get("region") or "").strip() or None
    use_llm, eval_spec = _llm_eval_from_brief(brief)
    interval_lo, interval_hi = outreach_interval_from_brief(brief)
    for lo_key, hi_key in (
        ("comment_dm_interval_seconds_min", "comment_dm_interval_seconds_max"),
        ("interval_min_sec", "interval_max_sec"),
        ("interval_min", "interval_max"),
    ):
        lo = brief.constraints.get(lo_key)
        hi = brief.constraints.get(hi_key)
        if lo is not None or hi is not None:
            interval_lo = max(1, int(lo or interval_lo))
            interval_hi = max(interval_lo, int(hi or interval_hi))
            break

            break

    comments_cap, scroll_rounds = _comment_browse_limits_from_brief(brief, params, target=target)
    config = build_standalone_browse_config(
        acquisition_mode=mode,
        keyword=str(params.get("keyword") or brief.keyword or "").strip(),
        video_url=video_url,
        profile_url=profile_url,
        input_url=str(brief.goals.get("input_url") or video_url or profile_url or "").strip(),
        days=days,
        video_publish_days=int(publish_days) if publish_days is not None else None,
        comment_days=int(comment_days) if comment_days is not None else None,
        target_precise_leads=target,
        max_videos_to_browse=video_limit,
        max_comments_per_video=comments_cap,
        comment_scroll_rounds=scroll_rounds,
        start_video_index=max(0, int(params.get("start_video_index") or 0)),
        resume_search_url=str(params.get("resume_search_url") or "").strip(),
        source_job_id=str(params.get("job_id") or params.get("source_job_id") or "").strip(),
        match_keywords=_match_keywords_from_brief(brief),
        exclude_keywords=_reject_keywords_from_brief(brief),
        execute_outreach=not validate_only,
        test_all_outreach=False,
        reply_text=reply_text,
        dm_text=dm_text,
        comment_ratio=comment_ratio,
        dm_ratio=dm_ratio,
        follow_ratio=follow_ratio,
        persist_to_db=True,
        close_browser_after=False,
    )
    config.region = region
    config.use_llm_eval = use_llm
    config.eval_spec = eval_spec
    config.task_brief = brief if use_llm else None
    config.action_policy = {
        **(config.action_policy or {}),
        "interval_min_sec": interval_lo,
        "interval_max_sec": interval_hi,
    }
    daily_reply = brief.constraints.get("daily_reply_limit") or brief.goals.get("daily_reply_limit")
    if daily_reply is not None:
        config.action_policy["daily_reply_limit"] = int(daily_reply)
    if brief.constraints.get("follow_per_day") is not None:
        config.action_policy["daily_follow_limit"] = int(brief.constraints.get("follow_per_day"))
    if brief.constraints.get("dm_per_day") is not None:
        config.action_policy["daily_dm_limit"] = int(brief.constraints.get("dm_per_day"))
    return config


def _lead_to_comment_block(lead: PreciseLeadRecord, *, keyword: str, mode: str) -> dict[str, Any]:
    raw = lead.raw_comment if isinstance(lead.raw_comment, dict) else {}
    comment_row = dict(raw) if raw else {
        "comment_id": lead.comment_id,
        "comment": lead.comment_text,
        "text": lead.comment_text,
        "username": lead.username,
        "user_id": lead.user_id,
        "sec_uid": lead.sec_uid,
        "create_time": lead.create_time,
    }
    return {
        "platform": "douyin",
        "aweme_id": lead.aweme_id,
        "video_url": lead.video_url,
        "comments": [comment_row],
        "keyword_context": {
            "keyword": keyword,
            "capture_mode": capture_method_for_mode(mode),
            "status": "precise",
        },
    }


def standalone_result_to_skill_result(
    result: StandaloneKeywordBrowseResult,
    *,
    brief: TaskBrief,
    action: str,
    outreach_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Standalone 结果 → Supervisor 可消费的 skill_result 形状。"""
    stats = outreach_stats or {}
    leads = list(result.precise_leads or [])
    executed = sum(1 for lead in leads if lead.outreach_executed)
    blocks: list[dict[str, Any]] = []
    seen_aweme: set[str] = set()
    for lead in leads:
        aid = str(lead.aweme_id or "")
        if aid and aid in seen_aweme:
            for block in blocks:
                if str(block.get("aweme_id") or "") == aid:
                    block["comments"].append(
                        (_lead_to_comment_block(lead, keyword=result.keyword, mode=result.acquisition_mode))["comments"][0]
                    )
                    break
            continue
        if aid:
            seen_aweme.add(aid)
        blocks.append(_lead_to_comment_block(lead, keyword=result.keyword, mode=result.acquisition_mode))

    ok = bool(result.ok or result.videos_processed > 0 or leads)
    status = "completed" if result.target_reached else ("partial" if ok else "failed")
    partial_continue = (
        ok
        and not result.target_reached
        and not result.search_exhausted
        and result.videos_processed > 0
    )
    error = result.error if not partial_continue else None
    summary_parts = [
        f"standalone 浏览 {result.videos_processed} 个视频",
        f"扫描评论 {result.comments_scanned}",
        f"精准线索 {len(leads)}/{int(brief.goals.get('target_leads') or 0) or '目标'}",
    ]
    if stats:
        summary_parts.append(
            f"触达 reply={stats.get('replies', 0)} dm={stats.get('dms', 0)} follow={stats.get('follows', 0)}"
        )
    if result.diagnostic:
        summary_parts.append(str(result.diagnostic)[:120])

    return {
        "status": status,
        "standalone_browse": True,
        "action": action,
        "summary": "；".join(summary_parts),
        "keyword": result.keyword or brief.keyword,
        "acquisition_mode": result.acquisition_mode,
        "videos_processed": result.videos_processed,
        "comments_scanned": result.comments_scanned,
        "raw_comments_scanned": result.comments_scanned,
        "total_comments_captured": result.comments_scanned,
        "precise_lead_count": len(leads),
        "comments_persisted": sum(1 for lead in leads if lead.persisted),
        "target_reached": result.target_reached,
        "results": blocks,
        "inline_outreach": {
            "replies": int(stats.get("replies") or 0),
            "dms": int(stats.get("dms") or 0),
            "follows": int(stats.get("follows") or 0),
            "executed": executed,
        },
        "outreach_executed_count": executed,
        "diagnostic": result.diagnostic,
        "error": error,
        "output_file": result.output_file,
        "crawl_search_exhausted": bool(result.search_exhausted or result.target_reached),
        "standalone_need_more": partial_continue,
        "start_video_index": int(getattr(result, "start_video_index", 0) or 0),
        "search_url": str(getattr(result, "search_url", "") or ""),
    }


async def run_standalone_browse_for_supervisor(
    settings: Settings,
    *,
    tenant_id: str,
    account_id: str,
    brief: TaskBrief,
    params: dict[str, Any],
    action: str,
    db_session: Session | None,
    state: dict[str, Any] | None = None,
    on_progress: Any = None,
) -> dict[str, Any]:
    merged_params = dict(params)
    if state and state.get("job_id") and "job_id" not in merged_params:
        merged_params["job_id"] = str(state.get("job_id") or "")
    offset = int((state or {}).get("standalone_browse_offset") or 0)
    if offset > 0 and "start_video_index" not in merged_params:
        merged_params["start_video_index"] = offset
    saved_search = str((state or {}).get("standalone_search_url") or "").strip()
    if saved_search and offset > 0 and "resume_search_url" not in merged_params:
        merged_params["resume_search_url"] = saved_search
    config = brief_to_standalone_config(brief, merged_params, action=action)
    headless = not show_browser(brief)
    result = await run_standalone_keyword_browse_with_browser(
        settings,
        tenant_id=tenant_id,
        account_id=account_id,
        config=config,
        db_session=db_session,
        headless=headless,
        on_progress=on_progress,
    )
    outreach_stats = {}
    for line in reversed(result.phase_log or []):
        if "outreach_stats" in line.lower():
            break
    # outreach counts live in output json; parse from phase or recompute from leads
    for lead in result.precise_leads or []:
        if not lead.outreach_executed:
            continue
        action_name = str(getattr(lead.planned_action, "value", lead.planned_action) or "")
        if action_name == "reply":
            outreach_stats["replies"] = outreach_stats.get("replies", 0) + 1
        elif action_name == "dm":
            outreach_stats["dms"] = outreach_stats.get("dms", 0) + 1
        elif action_name == "follow":
            outreach_stats["follows"] = outreach_stats.get("follows", 0) + 1

    skill_result = standalone_result_to_skill_result(
        result,
        brief=brief,
        action=action,
        outreach_stats=outreach_stats,
    )
    if skill_result.get("error") and skill_result.get("status") == "failed":
        skill_result.setdefault("status", "failed")
    return skill_result


def build_standalone_execution_plan(brief: TaskBrief, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """standalone 策略专用计划：一体化抓取+评估+触达 → 同步配额 → 结束。"""
    state = state or {}
    target = int(brief.goals.get("target_leads") or 0)
    video_limit = _standalone_max_videos_cap(
        brief, {}, target_leads=max(1, target), action="crawl_keyword",
    )
    limit_suffix = (
        f"；单步最多浏览 {video_limit} 个视频"
        if manual_acquisition_mode(brief) == "account_home"
        else ""
    )
    manual = manual_acquisition_mode(brief)
    input_url = str(
        brief.goals.get("input_url") or brief.goals.get("video_url") or brief.goals.get("profile_url") or ""
    ).strip()

    if manual == "single_video" or str(brief.goals.get("acquisition_mode") or "") == "single_video":
        crawl_action = "crawl_content_url"
        crawl_label = f"单视频一体化浏览（点击/直达 → 侧栏评估 → 同页触达）"
        crawl_params: dict[str, Any] = {
            "video_url": str(brief.goals.get("video_url") or input_url),
            **build_crawl_day_params(brief),
            "show_browser": show_browser(brief),
        }
    elif manual == "account_home" or str(brief.goals.get("acquisition_mode") or "") == "account_home":
        crawl_action = "crawl_profile"
        crawl_label = f"主页一体化浏览（点击作品列表 → 侧栏评估 → 同页触达）{limit_suffix}"
        crawl_params = {
            "profile_url": str(brief.goals.get("profile_url") or input_url),
            **build_crawl_day_params(brief),
            "show_browser": show_browser(brief),
        }
        apply_crawl_video_limit_aliases(crawl_params, video_limit)
    else:
        keyword = str(brief.keyword or "").strip() or "关键词"
        target_label = target if target > 0 else "配置"
        crawl_action = "crawl_keyword"
        crawl_label = (
            f"关键词「{keyword}」一体化浏览（搜索 → 点视频 → 侧栏评估 → 同页触达）；"
            f"目标 {target_label} 条精准线索，持续浏览发布时间内搜索结果视频"
        )
        crawl_params = {
            "keyword": keyword,
            "region": brief.region,
            **build_crawl_day_params(brief),
            "show_browser": show_browser(brief),
            "target_leads": max(1, target) if target > 0 else int(brief.goals.get("target_leads") or 5),
            "max_videos_to_browse": video_limit,
        }

    steps: list[dict[str, Any]] = [
        {
            "id": "crawl",
            "order": 1,
            "action": crawl_action,
            "label": crawl_label,
            "status": "completed" if state.get("crawl_done") else "pending",
            "required": True,
            "params": crawl_params,
        },
        {
            "id": "sync_stats",
            "order": 2,
            "action": "query_stats",
            "label": "同步今日 reply/follow/dm 触达配额",
            "status": "completed" if state.get("stats_synced") else "pending",
            "required": True,
            "params": {"platform": brief.platform or "douyin"},
        },
    ]
    from app.services.task_execution_plan import _outreach_steps

    outreach = _outreach_steps(brief, start_order=3)
    steps.extend(outreach)
    finish_order = 3 + len(outreach)
    steps.append(
        {
            "id": "finish",
            "order": finish_order,
            "action": "complete",
            "label": f"一体化流程结束（目标线索 ≥ {target or '配置'}）",
            "status": "pending",
            "required": True,
            "params": {},
        },
    )
    summary = (
        f"【{brief.title or '抖音获客'}】standalone 一体化："
        f" ①浏览+评估+同页触达 → ②同步配额 → ③补触达 reply/dm/follow → ④结束"
    )
    return {
        "summary": summary,
        "steps": steps,
        "current_index": _resolve_plan_index(steps),
        "version": STANDALONE_PLAN_VERSION,
        "pipeline": STANDALONE_PIPELINE,
    }


def _standalone_plan_needs_upgrade(plan: dict[str, Any]) -> bool:
    if int(plan.get("version") or 0) < STANDALONE_PLAN_VERSION:
        return True
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    from app.services.task_execution_plan import OUTREACH_LOOP_ACTIONS

    if not any(
        isinstance(step, dict) and str(step.get("action") or "") in OUTREACH_LOOP_ACTIONS
        for step in steps
    ):
        return True
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        label = str(step.get("label") or "")
        if "最多 5 个视频" in label or "最多 5个视频" in label:
            return True
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        if str(step.get("action") or "") == "crawl_keyword":
            limit = params.get("crawl_video_limit")
            target = params.get("target_leads")
            try:
                if limit is not None and target is not None and int(limit) == int(target):
                    return True
            except (TypeError, ValueError):
                pass
            if params.get("max_videos_to_browse") is None and limit is not None:
                return True
    return False


def upgrade_standalone_execution_plan(
    plan: dict[str, Any],
    brief: TaskBrief,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """升级旧 standalone 计划：目标=N 条精准线索，不再把 target 误标为视频上限。"""
    state = state if isinstance(state, dict) else {}
    fresh = build_standalone_execution_plan(brief, state)
    old_steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    new_steps = fresh.get("steps") if isinstance(fresh.get("steps"), list) else []
    status_by_id: dict[str, str] = {}
    for step in old_steps:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id") or "")
        status = str(step.get("status") or "")
        if sid and status:
            status_by_id[sid] = status
    for step in new_steps:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id") or "")
        if sid in status_by_id:
            step["status"] = status_by_id[sid]
    fresh["current_index"] = _resolve_plan_index(new_steps)
    return fresh


def _resolve_plan_index(steps: list[dict[str, Any]]) -> int:
    for idx, step in enumerate(steps):
        if step.get("status") not in {"completed", "skipped"}:
            return idx
    return max(len(steps) - 1, 0)
