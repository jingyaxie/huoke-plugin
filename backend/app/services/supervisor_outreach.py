from __future__ import annotations

import random
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.platforms.types import normalize_platform
from app.services.comment_store_service import CommentStoreService, extract_content_id
from app.services.interaction_log_service import InteractionLogService
from app.services.lead_evaluation_service import (
    accept_evaluation_result,
    evaluate_comments_batch,
    lead_evaluation_from_brief,
    min_comment_digg_from_brief,
)
from app.services.outreach_matcher import render_template, reply_template
from app.services.stored_comment_service import StoredCommentService
from app.services.task_brief_service import TaskBrief


def extract_crawl_payloads(skill_result: dict[str, Any]) -> list[dict[str, Any]]:
    """从抓取结果中提取可入库的评论块。"""
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_block(block: dict[str, Any]) -> None:
        if not isinstance(block, dict):
            return
        comments = block.get("comments") or block.get("comments_preview") or []
        if not isinstance(comments, list) or not comments:
            return
        content_url = str(
            block.get("video_url")
            or block.get("content_url")
            or block.get("note_url")
            or ""
        ).strip()
        content_id = str(
            block.get("aweme_id")
            or block.get("content_id")
            or block.get("note_id")
            or extract_content_id("douyin", content_url, block)
            or ""
        ).strip()
        if not content_id:
            return
        key = f"{content_id}:{len(comments)}"
        if key in seen:
            return
        seen.add(key)
        payloads.append(
            {
                "platform": block.get("platform") or "douyin",
                "aweme_id": content_id,
                "video_url": content_url,
                "comments": [row for row in comments if isinstance(row, dict)],
                "keyword_context": block.get("keyword_context") or {},
            }
        )

    for row in skill_result.get("results") or []:
        add_block(row)

    inner = skill_result.get("result")
    if isinstance(inner, dict):
        for row in inner.get("comments_by_video") or []:
            add_block(row)
        if inner.get("comments"):
            add_block(inner)

    for row in skill_result.get("comments_by_video") or []:
        add_block(row)

    return payloads


def extract_comment_ids_from_skill_result(skill_result: dict[str, Any]) -> list[str]:
    """从抓取结果提取 comment_id（用于任务级入库清单）。"""
    ids: list[str] = []
    seen: set[str] = set()
    for payload in extract_crawl_payloads(skill_result):
        for row in payload.get("comments") or []:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("comment_id") or "").strip()
            if cid and cid not in seen:
                seen.add(cid)
                ids.append(cid)
    return ids


def merge_job_persisted_comment_ids(state: dict[str, Any], skill_result: dict[str, Any]) -> None:
    """记录本任务本次抓取写入/更新的 comment_id，供前端按 job 展示。"""
    ids = extract_comment_ids_from_skill_result(skill_result)
    if not ids:
        return
    existing = {
        str(x).strip() for x in (state.get("job_persisted_comment_ids") or []) if str(x).strip()
    }
    existing.update(ids)
    state["job_persisted_comment_ids"] = sorted(existing)[-5000:]


def count_crawl_comments(skill_result: dict[str, Any]) -> int:
    count = sum(len(payload.get("comments") or []) for payload in extract_crawl_payloads(skill_result))
    if count > 0:
        return count
    top = int(skill_result.get("total_comments_captured") or 0)
    if top > 0:
        return top
    total = 0
    for row in skill_result.get("results") or []:
        if isinstance(row, dict):
            total += int(row.get("total_comments_captured") or 0)
    return total


def _is_search_results_url(url: str | None) -> bool:
    u = (url or "").lower()
    return "/search/" in u or "/jingxuan/search/" in u or "search_result" in u


def extract_discovered_video_urls(skill_result: dict[str, Any]) -> list[str]:
    """搜索阶段发现的视频 URL（与评论抓取结果解耦）。"""
    raw = skill_result.get("discovered_video_urls")
    urls: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            clean = str(item or "").strip().split("?")[0]
            if clean and clean not in seen:
                seen.add(clean)
                urls.append(clean)
        if urls:
            return urls
    for row in skill_result.get("results") or []:
        if not isinstance(row, dict):
            continue
        clean = str(
            row.get("video_url") or row.get("content_url") or row.get("note_url") or ""
        ).strip().split("?")[0]
        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)
    aweme_ids = skill_result.get("search_aweme_ids")
    if isinstance(aweme_ids, list):
        for aid in aweme_ids:
            token = str(aid or "").strip().split("?")[0]
            if not token:
                continue
            clean = f"https://www.douyin.com/video/{token}"
            if clean not in seen:
                seen.add(clean)
                urls.append(clean)
    return urls


def crawl_search_phase_succeeded(skill_result: dict[str, Any]) -> bool:
    """搜索阶段已成功：有结果页 URL 且发现至少 1 条视频链接。"""
    if skill_result.get("search_succeeded") is False:
        return False
    urls = extract_discovered_video_urls(skill_result)
    if not urls and int(skill_result.get("discovered_video_count") or 0) <= 0:
        return False
    if skill_result.get("search_succeeded") is True:
        return True
    search_url = str(skill_result.get("search_url") or "").strip()
    if _is_search_results_url(search_url) and (urls or int(skill_result.get("discovered_video_count") or 0) > 0):
        return True
    return False


def validate_crawl_skill_result(skill_result: dict[str, Any]) -> tuple[bool, str, int]:
    if skill_result.get("standalone_browse"):
        count = int(skill_result.get("precise_lead_count") or 0)
        videos = int(skill_result.get("videos_processed") or 0)
        scanned = int(skill_result.get("comments_scanned") or skill_result.get("total_comments_captured") or 0)
        if videos > 0 or count > 0 or scanned > 0:
            return True, "", max(count, scanned)
        if str(skill_result.get("status") or "").lower() in {"completed", "partial"}:
            return True, "", count
        return False, str(skill_result.get("error") or skill_result.get("diagnostic") or "standalone 浏览未产生有效结果"), 0
    videos = int(skill_result.get("videos_processed") or 0)
    count = count_crawl_comments(skill_result)
    if videos > 0 and count >= 0:
        return True, "", count
    if count > 0:
        return True, "", count
    if crawl_search_phase_succeeded(skill_result):
        return True, "", 0
    return (
        False,
        "抓取结果缺少 comments 结构化数据或未浏览任何视频，无法入库",
        0,
    )


def persist_crawl_skill_result(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    skill_result: dict[str, Any],
    source_job_id: str | None = None,
    source_keyword: str | None = None,
) -> int:
    platform_norm = normalize_platform(platform)
    store = CommentStoreService(db_session, settings, tenant_id=tenant_id)
    jid = str(
        source_job_id
        or skill_result.get("job_id")
        or skill_result.get("task_id")
        or ""
    ).strip()
    keyword = str(
        source_keyword
        or skill_result.get("keyword")
        or ""
    ).strip()
    total = 0
    for payload in extract_crawl_payloads(skill_result):
        content_url = str(payload.get("video_url") or payload.get("note_url") or "").strip()
        content_id = str(payload.get("aweme_id") or payload.get("note_id") or "").strip()
        if not content_id:
            content_id = extract_content_id(platform_norm, content_url, payload) or ""
        if not content_id:
            continue
        kw_ctx = payload.get("keyword_context")
        kw = keyword
        if not kw and isinstance(kw_ctx, dict):
            kw = str(kw_ctx.get("keyword") or kw_ctx.get("search_keyword") or "").strip()
        _, _, stats = store.merge_and_persist(
            platform=platform_norm,
            content_id=content_id,
            content_url=content_url,
            fetched_payload=payload,
            source_job_id=jid or None,
            source_keyword=kw or None,
        )
        total += int(stats.new_comments_added or 0) + int(stats.updated_comments or 0)
    if total:
        db_session.commit()
    return total


def outreach_scope_from_brief(brief: TaskBrief) -> str:
    """触达评论来源：job=仅本任务入库；pool=租户评论池。"""
    raw = brief.constraints.get("outreach_scope")
    if raw is None:
        raw = brief.goals.get("outreach_scope")
    if raw in (None, ""):
        return "job"
    return str(raw).strip().lower()


def _comment_row_job_id(row: dict[str, Any]) -> str:
    raw = row.get("raw_data") if isinstance(row.get("raw_data"), dict) else {}
    meta = raw.get("_agent_meta") if isinstance(raw.get("_agent_meta"), dict) else {}
    return str(meta.get("source_job_id") or "").strip()


def _row_in_outreach_scope(row: dict[str, Any], *, job_id: str, scope: str) -> bool:
    if scope in {"pool", "tenant", "global", "all"}:
        return True
    if not job_id:
        return True
    stored = _comment_row_job_id(row)
    if stored:
        return stored == job_id
    return False


def _agent_meta_for_persist(
    *,
    source_job_id: str | None = None,
    source_keyword: str | None = None,
) -> dict[str, str]:
    meta: dict[str, str] = {}
    jid = str(source_job_id or "").strip()
    if jid:
        meta["source_job_id"] = jid
    kw = str(source_keyword or "").strip()
    if kw:
        meta["source_keyword"] = kw
    return meta


def min_comment_digg_from_brief(brief: TaskBrief) -> int:
    for key in ("min_comment_digg",):
        val = brief.goals.get(key)
        if val is not None:
            return max(0, int(val))
        val = brief.constraints.get(key)
        if val is not None:
            return max(0, int(val))
    return 0


def skip_replied_comments_enabled(brief: TaskBrief) -> bool:
    val = brief.constraints.get("skip_replied_comments")
    if val is None:
        return True
    return bool(val)


def follow_before_dm_enabled(brief: TaskBrief) -> bool:
    return bool(brief.constraints.get("follow_before_dm"))


def outreach_priority_from_brief(brief: TaskBrief) -> list[str]:
    raw = brief.constraints.get("outreach_priority")
    if isinstance(raw, list) and raw:
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip().lower()]
    return ["reply", "dm", "follow"]


def _interval_bounds_from_mapping(mapping: dict[str, Any]) -> tuple[Any, Any]:
    """兼容 interval_min / interval_min_sec 两套字段名（前端 constraints 常用前者）。"""
    lo = mapping.get("interval_min_sec")
    if lo is None:
        lo = mapping.get("interval_min")
    hi = mapping.get("interval_max_sec")
    if hi is None:
        hi = mapping.get("interval_max")
    return lo, hi


def outreach_interval_from_brief(brief: TaskBrief) -> tuple[int, int]:
    sim = brief.goals.get("ui_timing")
    if isinstance(sim, dict):
        lo, hi = _interval_bounds_from_mapping(sim)
        if lo is not None or hi is not None:
            low = max(1, int(lo or 30))
            high = max(low, int(hi or low))
            return low, high
    lo, hi = _interval_bounds_from_mapping(brief.constraints)
    low = max(1, int(lo or 30))
    high = max(low, int(hi or 120))
    return low, high


def max_run_days_from_brief(brief: TaskBrief) -> int:
    for key in ("max_run_days",):
        val = brief.constraints.get(key)
        if val is not None:
            return max(0, int(val))
        val = brief.goals.get(key)
        if val is not None:
            return max(0, int(val))
    return 0


def outreach_bucket_can_do(bucket: dict[str, Any]) -> bool:
    if bucket.get("can_do") is not None:
        return bool(bucket.get("can_do"))
    if bucket.get("quota_ok") is not None:
        return bool(bucket.get("quota_ok"))
    limit = bucket.get("limit")
    count = bucket.get("count")
    if limit is not None and count is not None:
        try:
            return int(count) < int(limit)
        except (TypeError, ValueError):
            pass
    return False


def outreach_stats_ready(stats: dict[str, Any], brief: TaskBrief) -> bool:
    for action in outreach_priority_from_brief(brief):
        if isinstance(stats.get(action), dict):
            return True
    return False


def next_outreach_action_from_brief(
    stats: dict[str, Any],
    brief: TaskBrief,
) -> str | None:
    if not outreach_stats_ready(stats, brief):
        return None
    for action in outreach_priority_from_brief(brief):
        bucket = stats.get(action) if isinstance(stats.get(action), dict) else {}
        if outreach_bucket_can_do(bucket):
            return action
    return None


def outreach_quotas_exhausted(stats: dict[str, Any], brief: TaskBrief) -> bool:
    if not outreach_stats_ready(stats, brief):
        return False
    for action in outreach_priority_from_brief(brief):
        bucket = stats.get(action) if isinstance(stats.get(action), dict) else {}
        if outreach_bucket_can_do(bucket):
            return False
    return True


def comment_match_from_brief(brief: TaskBrief) -> dict[str, Any]:
    """兼容旧 import 名；返回 lead_evaluation spec。"""
    return lead_evaluation_from_brief(brief)


def _pick_constraint_template(brief: TaskBrief, plural_key: str, singular_key: str, fallback: str) -> str:
    templates = brief.constraints.get(plural_key)
    if isinstance(templates, list) and templates:
        texts = [str(item).strip() for item in templates if str(item).strip()]
        if texts:
            return random.choice(texts)
    single = str(brief.constraints.get(singular_key) or brief.goals.get(singular_key) or "").strip()
    return single or fallback


def actions_on_match_from_brief(brief: TaskBrief) -> list[dict[str, Any]]:
    raw = brief.constraints.get("actions_on_match")
    if isinstance(raw, list) and raw:
        return raw
    template = _pick_constraint_template(
        brief,
        "reply_templates",
        "reply_template",
        "",
    )
    if template:
        return [{"type": "reply", "template": template}]
    return [{"type": "reply", "template": "您好 {{nickname}}，看到您咨询「{{comment}}」，可以私信发您案例和报价～"}]


def build_reply_text(brief: TaskBrief, *, nickname: str, comment: str) -> str:
    templates = brief.constraints.get("reply_templates")
    if isinstance(templates, list) and templates:
        texts = [str(item).strip() for item in templates if str(item).strip()]
        if texts:
            template = random.choice(texts)
            return render_template(template, nickname=nickname or "朋友", comment=comment or "")
    template = reply_template(actions_on_match_from_brief(brief))
    return render_template(template, nickname=nickname or "朋友", comment=comment or "")


def build_dm_text(brief: TaskBrief, *, nickname: str, comment: str) -> str:
    template = _pick_constraint_template(
        brief,
        "dm_templates",
        "dm_template",
        "",
    )
    if not template:
        template = str(brief.constraints.get("reply_template") or "").strip()
    if not template:
        template = "您好 {{nickname}}，看到您关注相关业务，方便聊聊吗？"
    return render_template(template, nickname=nickname or "朋友", comment=comment or "")


def _user_ids_from_comment_row(row: dict[str, Any]) -> tuple[str, str]:
    user_id = str(row.get("user_id") or row.get("reply_to_user_id") or "").strip()
    sec_uid = str(row.get("sec_uid") or "").strip()
    raw = row.get("raw_data")
    if isinstance(raw, dict):
        if not user_id:
            user_id = str(raw.get("user_id") or "").strip()
        if not sec_uid:
            sec_uid = str(raw.get("sec_uid") or "").strip()
        user = raw.get("user")
        if isinstance(user, dict):
            if not user_id:
                user_id = str(user.get("uid") or user.get("user_id") or "").strip()
            if not sec_uid:
                sec_uid = str(user.get("sec_uid") or "").strip()
    return user_id, sec_uid


def _evaluation_cache_from_state(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("evaluation_cache")
    if isinstance(raw, dict):
        return dict(raw)
    legacy = state.get("llm_intent_cache")
    return dict(legacy) if isinstance(legacy, dict) else {}


def _passes_comment_row_filters(
    row: dict[str, Any],
    *,
    eval_spec: dict[str, Any],
    min_digg: int,
    evaluation_cache: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    comment_id = str(row.get("comment_id") or "").strip()
    cached = (evaluation_cache or {}).get(comment_id) if isinstance(evaluation_cache, dict) else None
    if not isinstance(cached, dict):
        return False, "evaluation_pending"
    if accept_evaluation_result(cached, eval_spec):
        if min_digg > 0:
            digg = int(row.get("digg_count") or 0)
            if digg < min_digg:
                return False, f"digg<{min_digg}"
        return True, "llm_evaluation"
    return False, str(cached.get("reason") or "not_lead")


def _iter_matched_comment_rows(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    brief: TaskBrief,
    state: dict[str, Any],
    limit: int = 120,
) -> list[dict[str, Any]]:
    """同步路径：仅返回 evaluation_cache 中已评估且通过的评论。"""
    try:
        eval_spec = lead_evaluation_from_brief(brief)
    except ValueError:
        return []
    platform_norm = normalize_platform(platform)
    min_digg = min_comment_digg_from_brief(brief)
    scope = outreach_scope_from_brief(brief)
    job_id = str(state.get("job_id") or "").strip()
    skip_ids = set(state.get("outreach_skip_comment_ids") or [])
    if isinstance(state.get("failed_comment_ids"), list):
        skip_ids.update(str(x) for x in state["failed_comment_ids"] if x)

    evaluation_cache = _evaluation_cache_from_state(state)
    if not evaluation_cache:
        return []

    stored = StoredCommentService(db_session, settings, tenant_id=tenant_id)
    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    batch_size = 50
    max_scan = max(limit * 4, 300)
    offset = 0
    scanned = 0

    while len(matched) < limit and scanned < max_scan:
        query = stored.query_comments(
            platform=platform_norm,
            offset=offset,
            limit=batch_size,
        )
        comments = query.get("comments") or []
        if not comments:
            break
        scanned += len(comments)
        for row in comments:
            if not isinstance(row, dict):
                continue
            comment_id = str(row.get("comment_id") or "").strip()
            if not comment_id or comment_id in skip_ids or comment_id in seen_ids:
                continue
            if row.get("parent_comment_id"):
                continue
            if not _row_in_outreach_scope(row, job_id=job_id, scope=scope):
                continue
            ok, _reason = _passes_comment_row_filters(
                row,
                eval_spec=eval_spec,
                min_digg=min_digg,
                evaluation_cache=evaluation_cache,
            )
            if ok:
                seen_ids.add(comment_id)
                matched.append(row)
                if len(matched) >= limit:
                    break
        if len(comments) < batch_size:
            break
        offset += batch_size

    return matched[:limit]


async def run_evaluate_leads_phase(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    brief: TaskBrief,
    state: dict[str, Any],
    provider: str | None = None,
    max_scan: int = 400,
) -> dict[str, Any]:
    """internal.evaluate_leads：批量 LLM 评估入库评论并写入 cache。"""
    eval_spec = lead_evaluation_from_brief(brief)
    platform_norm = normalize_platform(platform)
    scope = outreach_scope_from_brief(brief)
    job_id = str(state.get("job_id") or "").strip()
    evaluation_cache = _evaluation_cache_from_state(state)
    allowed_content = {
        str(x).strip()
        for key in ("job_content_ids", "watched_content_ids")
        for x in (state.get(key) or [])
        if str(x).strip()
    }

    stored = StoredCommentService(db_session, settings, tenant_id=tenant_id)
    candidates: list[dict[str, Any]] = []
    batch_size = 40
    offset = 0
    scanned = 0

    while scanned < max_scan:
        query = stored.query_comments(
            platform=platform_norm,
            offset=offset,
            limit=batch_size,
        )
        comments = query.get("comments") or []
        if not comments:
            break
        scanned += len(comments)
        for row in comments:
            if not isinstance(row, dict):
                continue
            comment_id = str(row.get("comment_id") or "").strip()
            if not comment_id or comment_id in evaluation_cache:
                continue
            if row.get("parent_comment_id"):
                continue
            if not _row_in_outreach_scope(row, job_id=job_id, scope=scope):
                continue
            if allowed_content:
                row_content_id = str(row.get("content_id") or "").strip()
                if row_content_id and row_content_id not in allowed_content:
                    continue
            candidates.append(row)
        if len(comments) < batch_size:
            break
        offset += batch_size

    evaluated = 0
    qualified = 0
    if candidates:
        classified = await evaluate_comments_batch(
            candidates,
            eval_spec,
            brief,
            settings=settings,
            provider=provider,
        )
        evaluation_cache.update(classified)
        evaluated = len(classified)
        job_comment_ids = {
            str(x).strip() for x in (state.get("job_evaluation_comment_ids") or []) if str(x).strip()
        }
        job_content_ids = {
            str(x).strip() for x in (state.get("job_content_ids") or []) if str(x).strip()
        }
        for row in candidates:
            comment_id = str(row.get("comment_id") or "").strip()
            if comment_id:
                job_comment_ids.add(comment_id)
            content_id = str(row.get("content_id") or "").strip()
            if content_id:
                job_content_ids.add(content_id)
        state["job_evaluation_comment_ids"] = sorted(job_comment_ids)[-3000:]
        if job_content_ids:
            state["job_content_ids"] = sorted(job_content_ids)[-500:]
        qualified = sum(
            1 for cid in job_comment_ids
            if accept_evaluation_result(evaluation_cache.get(cid) or {}, eval_spec)
        )
    else:
        job_comment_ids = {
            str(x).strip() for x in (state.get("job_evaluation_comment_ids") or []) if str(x).strip()
        }
        qualified = sum(
            1 for cid in job_comment_ids
            if accept_evaluation_result(evaluation_cache.get(cid) or {}, eval_spec)
        )

    if evaluation_cache:
        state["evaluation_cache"] = dict(list(evaluation_cache.items())[-1200:])
    state["comments_evaluated"] = int(state.get("comments_evaluated") or 0) + evaluated
    state["leads_qualified"] = qualified
    state["evaluation_done"] = True

    return {
        "status": "ok",
        "evaluated": evaluated,
        "qualified": qualified,
        "cache_size": len(evaluation_cache),
        "summary": f"评估 {evaluated} 条评论，{qualified} 条符合触达标准",
    }


async def iter_matched_comment_rows_async(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    brief: TaskBrief,
    state: dict[str, Any],
    limit: int = 120,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """匹配待触达评论：LLM 评估缓存 + 语义筛选。"""
    eval_spec = lead_evaluation_from_brief(brief)
    platform_norm = normalize_platform(platform)
    min_digg = min_comment_digg_from_brief(brief)
    scope = outreach_scope_from_brief(brief)
    job_id = str(state.get("job_id") or "").strip()
    skip_ids = set(state.get("outreach_skip_comment_ids") or [])
    if isinstance(state.get("failed_comment_ids"), list):
        skip_ids.update(str(x) for x in state["failed_comment_ids"] if x)

    evaluation_cache = _evaluation_cache_from_state(state)

    stored = StoredCommentService(db_session, settings, tenant_id=tenant_id)
    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    batch_size = 40
    max_scan = max(limit * 8, 400)
    offset = 0
    scanned = 0

    while len(matched) < limit and scanned < max_scan:
        query = stored.query_comments(
            platform=platform_norm,
            offset=offset,
            limit=batch_size,
        )
        comments = query.get("comments") or []
        if not comments:
            break
        scanned += len(comments)

        candidates: list[dict[str, Any]] = []
        for row in comments:
            if not isinstance(row, dict):
                continue
            comment_id = str(row.get("comment_id") or "").strip()
            if not comment_id or comment_id in skip_ids or comment_id in seen_ids:
                continue
            if row.get("parent_comment_id"):
                continue
            if not _row_in_outreach_scope(row, job_id=job_id, scope=scope):
                continue
            candidates.append(row)

        uncached = [r for r in candidates if str(r.get("comment_id") or "") not in evaluation_cache]
        if uncached:
            classified = await evaluate_comments_batch(
                uncached,
                eval_spec,
                brief,
                settings=settings,
                provider=provider,
            )
            evaluation_cache.update(classified)

        for row in candidates:
            comment_id = str(row.get("comment_id") or "").strip()
            ok, _reason = _passes_comment_row_filters(
                row,
                eval_spec=eval_spec,
                min_digg=min_digg,
                evaluation_cache=evaluation_cache,
            )
            if ok:
                seen_ids.add(comment_id)
                matched.append(row)
                if len(matched) >= limit:
                    break

        if len(comments) < batch_size:
            break
        offset += batch_size

    if evaluation_cache:
        state["evaluation_cache"] = dict(list(evaluation_cache.items())[-1200:])
    return matched[:limit]


def pick_outreach_reply_target(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    account_id: str,
    brief: TaskBrief,
    state: dict[str, Any],
    limit: int = 80,
) -> dict[str, Any] | None:
    platform_norm = normalize_platform(platform)
    log_service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
    skip_replied = skip_replied_comments_enabled(brief)

    for row in _iter_matched_comment_rows(
        db_session,
        settings,
        tenant_id=tenant_id,
        platform=platform,
        brief=brief,
        state=state,
        limit=limit,
    ):
        comment_id = str(row.get("comment_id") or "").strip()
        if skip_replied and log_service.is_comment_replied(
            platform=platform_norm,
            comment_id=comment_id,
            account_id=account_id,
        ):
            continue
        text = str(row.get("comment") or row.get("comment_text") or "").strip()
        content_id = str(row.get("content_id") or "").strip()
        video_url = str(row.get("content_url") or row.get("video_url") or "").strip()
        nickname = str(row.get("nickname") or "").strip()
        return {
            "comment_id": comment_id,
            "content_id": content_id or None,
            "video_url": video_url or None,
            "comment_text": text,
            "reply_text": build_reply_text(brief, nickname=nickname, comment=text),
        }
    return None


def pick_outreach_user_target(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    account_id: str,
    brief: TaskBrief,
    state: dict[str, Any],
    action: str,
    limit: int = 120,
) -> dict[str, Any] | None:
    platform_norm = normalize_platform(platform)
    log_service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
    action = action.strip().lower()
    touched_users = set(state.get("outreach_touched_user_ids") or [])
    if isinstance(state.get("failed_user_ids"), list):
        touched_users.update(str(x) for x in state["failed_user_ids"] if x)

    for row in _iter_matched_comment_rows(
        db_session,
        settings,
        tenant_id=tenant_id,
        platform=platform,
        brief=brief,
        state=state,
        limit=limit,
    ):
        user_id, sec_uid = _user_ids_from_comment_row(row)
        if not user_id and not sec_uid:
            continue
        user_key = sec_uid or user_id
        if user_key in touched_users:
            continue
        comment_id = str(row.get("comment_id") or "").strip()
        text = str(row.get("comment") or row.get("comment_text") or "").strip()
        nickname = str(row.get("nickname") or "").strip()
        content_id = str(row.get("content_id") or "").strip()
        video_url = str(row.get("content_url") or row.get("video_url") or "").strip()
        if action == "dm":
            if platform_norm == "xiaohongshu":
                continue
            if log_service.is_user_dmed(
                platform=platform_norm,
                target_user_id=user_id or None,
                target_sec_uid=sec_uid or None,
                account_id=account_id,
            ):
                continue
            if follow_before_dm_enabled(brief) and not log_service.is_user_followed(
                platform=platform_norm,
                target_user_id=user_id or None,
                target_sec_uid=sec_uid or None,
                account_id=account_id,
            ):
                continue
            if platform_norm == "douyin" and not sec_uid:
                continue
            return {
                "comment_id": comment_id,
                "user_id": user_id or None,
                "sec_uid": sec_uid or None,
                "username": nickname or None,
                "message": build_dm_text(brief, nickname=nickname, comment=text),
                "comment_text": text,
                "content_id": content_id or None,
                "content_url": video_url or None,
                "video_url": video_url or None,
            }
        if action == "follow":
            if log_service.is_user_followed(
                platform=platform_norm,
                target_user_id=user_id or None,
                target_sec_uid=sec_uid or None,
                account_id=account_id,
            ):
                continue
            if platform_norm == "douyin" and not sec_uid:
                continue
            if platform_norm == "xiaohongshu" and not user_id:
                continue
            return {
                "comment_id": comment_id,
                "user_id": user_id or None,
                "sec_uid": sec_uid or None,
                "username": nickname or None,
                "comment_text": text,
                "content_id": content_id or None,
                "content_url": video_url or None,
                "video_url": video_url or None,
            }
    return None


def pick_outreach_target_params(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    account_id: str,
    brief: TaskBrief,
    state: dict[str, Any],
    action: str,
) -> dict[str, Any] | None:
    action = str(action or "").strip().lower()
    if action == "reply":
        return pick_outreach_reply_target(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            brief=brief,
            state=state,
        )
    if action in {"dm", "follow"}:
        return pick_outreach_user_target(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            brief=brief,
            state=state,
            action=action,
        )
    return None


def resolve_outreach_action_with_policy(
    stats: dict[str, Any],
    brief: TaskBrief,
    *,
    db_session: Session | None,
    settings: Settings,
    tenant_id: str,
    platform: str,
    account_id: str,
    state: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, str]:
    if db_session is None:
        return None, None, "触达需要数据库会话"

    next_action = next_outreach_action_from_brief(stats, brief)
    if not next_action:
        if not outreach_stats_ready(stats, brief):
            return None, None, "触达前需先 query_stats 同步今日配额"
        if outreach_quotas_exhausted(stats, brief):
            return None, None, "今日触达配额已用尽"
        return None, None, "无可用触达方式（请检查 outreach_priority 配置）"

    if next_action == "dm" and follow_before_dm_enabled(brief):
        follow_bucket = stats.get("follow") if isinstance(stats.get("follow"), dict) else {}
        if outreach_bucket_can_do(follow_bucket):
            log_service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
            platform_norm = normalize_platform(platform)
            for row in _iter_matched_comment_rows(
                db_session,
                settings,
                tenant_id=tenant_id,
                platform=platform,
                brief=brief,
                state=state,
                limit=40,
            ):
                user_id, sec_uid = _user_ids_from_comment_row(row)
                if log_service.is_user_dmed(
                    platform=platform_norm,
                    target_user_id=user_id or None,
                    target_sec_uid=sec_uid or None,
                    account_id=account_id,
                ):
                    continue
                if not log_service.is_user_followed(
                    platform=platform_norm,
                    target_user_id=user_id or None,
                    target_sec_uid=sec_uid or None,
                    account_id=account_id,
                ):
                    params = pick_outreach_user_target(
                        db_session,
                        settings,
                        tenant_id=tenant_id,
                        platform=platform,
                        account_id=account_id,
                        brief=brief,
                        state=state,
                        action="follow",
                    )
                    if params:
                        return "follow", params, "私信前先关注（follow_before_dm）"
                    break

    params = pick_outreach_target_params(
        db_session,
        settings,
        tenant_id=tenant_id,
        platform=platform,
        account_id=account_id,
        brief=brief,
        state=state,
        action=next_action,
    )
    if params:
        return next_action, params, f"按优先级 {next_action} 触达"

    for fallback in outreach_priority_from_brief(brief):
        bucket = stats.get(fallback) if isinstance(stats.get(fallback), dict) else {}
        if not outreach_bucket_can_do(bucket):
            continue
        if fallback == next_action:
            continue
        params = pick_outreach_target_params(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            brief=brief,
            state=state,
            action=fallback,
        )
        if params:
            return fallback, params, f"优先 {next_action} 无目标，改 {fallback}"

    return None, None, "已入库评论中无匹配待触达线索"


async def pick_outreach_reply_target_async(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    account_id: str,
    brief: TaskBrief,
    state: dict[str, Any],
    limit: int = 80,
    provider: str | None = None,
) -> dict[str, Any] | None:
    platform_norm = normalize_platform(platform)
    log_service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
    skip_replied = skip_replied_comments_enabled(brief)

    rows = await iter_matched_comment_rows_async(
        db_session,
        settings,
        tenant_id=tenant_id,
        platform=platform,
        brief=brief,
        state=state,
        limit=limit,
        provider=provider,
    )
    for row in rows:
        comment_id = str(row.get("comment_id") or "").strip()
        if skip_replied and log_service.is_comment_replied(
            platform=platform_norm,
            comment_id=comment_id,
            account_id=account_id,
        ):
            continue
        text = str(row.get("comment") or row.get("comment_text") or "").strip()
        content_id = str(row.get("content_id") or "").strip()
        video_url = str(row.get("content_url") or row.get("video_url") or "").strip()
        nickname = str(row.get("nickname") or "").strip()
        return {
            "comment_id": comment_id,
            "content_id": content_id or None,
            "video_url": video_url or None,
            "comment_text": text,
            "reply_text": build_reply_text(brief, nickname=nickname, comment=text),
        }
    return None


async def pick_outreach_user_target_async(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    account_id: str,
    brief: TaskBrief,
    state: dict[str, Any],
    action: str,
    limit: int = 120,
    provider: str | None = None,
) -> dict[str, Any] | None:
    platform_norm = normalize_platform(platform)
    log_service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
    action = action.strip().lower()
    touched_users = set(state.get("outreach_touched_user_ids") or [])
    if isinstance(state.get("failed_user_ids"), list):
        touched_users.update(str(x) for x in state["failed_user_ids"] if x)

    rows = await iter_matched_comment_rows_async(
        db_session,
        settings,
        tenant_id=tenant_id,
        platform=platform,
        brief=brief,
        state=state,
        limit=limit,
        provider=provider,
    )
    for row in rows:
        user_id, sec_uid = _user_ids_from_comment_row(row)
        if not user_id and not sec_uid:
            continue
        user_key = sec_uid or user_id
        if user_key in touched_users:
            continue
        comment_id = str(row.get("comment_id") or "").strip()
        text = str(row.get("comment") or row.get("comment_text") or "").strip()
        nickname = str(row.get("nickname") or "").strip()
        if action == "dm":
            if platform_norm == "xiaohongshu":
                continue
            if log_service.is_user_dmed(
                platform=platform_norm,
                target_user_id=user_id or None,
                target_sec_uid=sec_uid or None,
                account_id=account_id,
            ):
                continue
            if follow_before_dm_enabled(brief) and not log_service.is_user_followed(
                platform=platform_norm,
                target_user_id=user_id or None,
                target_sec_uid=sec_uid or None,
                account_id=account_id,
            ):
                continue
            if platform_norm == "douyin" and not sec_uid:
                continue
            return {
                "comment_id": comment_id,
                "user_id": user_id or None,
                "sec_uid": sec_uid or None,
                "username": nickname or None,
                "message": build_dm_text(brief, nickname=nickname, comment=text),
                "comment_text": text,
            }
        if action == "follow":
            if log_service.is_user_followed(
                platform=platform_norm,
                target_user_id=user_id or None,
                target_sec_uid=sec_uid or None,
                account_id=account_id,
            ):
                continue
            if platform_norm == "douyin" and not sec_uid:
                continue
            if platform_norm == "xiaohongshu" and not user_id:
                continue
            return {
                "comment_id": comment_id,
                "user_id": user_id or None,
                "sec_uid": sec_uid or None,
                "username": nickname or None,
                "comment_text": text,
            }
    return None


async def pick_outreach_target_params_async(
    db_session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    account_id: str,
    brief: TaskBrief,
    state: dict[str, Any],
    action: str,
    provider: str | None = None,
) -> dict[str, Any] | None:
    action = str(action or "").strip().lower()
    if action == "reply":
        return await pick_outreach_reply_target_async(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            brief=brief,
            state=state,
            provider=provider,
        )
    if action in {"dm", "follow"}:
        return await pick_outreach_user_target_async(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            brief=brief,
            state=state,
            action=action,
            provider=provider,
        )
    return None


async def resolve_outreach_action_with_policy_async(
    stats: dict[str, Any],
    brief: TaskBrief,
    *,
    db_session: Session | None,
    settings: Settings,
    tenant_id: str,
    platform: str,
    account_id: str,
    state: dict[str, Any],
    provider: str | None = None,
) -> tuple[str | None, dict[str, Any] | None, str]:
    if db_session is None:
        return None, None, "触达需要数据库会话"

    next_action = next_outreach_action_from_brief(stats, brief)
    if not next_action:
        if not outreach_stats_ready(stats, brief):
            return None, None, "触达前需先 query_stats 同步今日配额"
        if outreach_quotas_exhausted(stats, brief):
            return None, None, "今日触达配额已用尽"
        return None, None, "无可用触达方式（请检查 outreach_priority 配置）"

    if next_action == "dm" and follow_before_dm_enabled(brief):
        follow_bucket = stats.get("follow") if isinstance(stats.get("follow"), dict) else {}
        if outreach_bucket_can_do(follow_bucket):
            log_service = InteractionLogService(db_session, settings, tenant_id=tenant_id)
            platform_norm = normalize_platform(platform)
            rows = await iter_matched_comment_rows_async(
                db_session,
                settings,
                tenant_id=tenant_id,
                platform=platform,
                brief=brief,
                state=state,
                limit=40,
                provider=provider,
            )
            for row in rows:
                user_id, sec_uid = _user_ids_from_comment_row(row)
                if log_service.is_user_dmed(
                    platform=platform_norm,
                    target_user_id=user_id or None,
                    target_sec_uid=sec_uid or None,
                    account_id=account_id,
                ):
                    continue
                if not log_service.is_user_followed(
                    platform=platform_norm,
                    target_user_id=user_id or None,
                    target_sec_uid=sec_uid or None,
                    account_id=account_id,
                ):
                    params = await pick_outreach_user_target_async(
                        db_session,
                        settings,
                        tenant_id=tenant_id,
                        platform=platform,
                        account_id=account_id,
                        brief=brief,
                        state=state,
                        action="follow",
                        provider=provider,
                    )
                    if params:
                        return "follow", params, "私信前先关注（follow_before_dm）"
                    break

    params = await pick_outreach_target_params_async(
        db_session,
        settings,
        tenant_id=tenant_id,
        platform=platform,
        account_id=account_id,
        brief=brief,
        state=state,
        action=next_action,
        provider=provider,
    )
    if params:
        note = f"LLM 评估通过后按 {next_action} 触达"
        return next_action, params, note

    for fallback in outreach_priority_from_brief(brief):
        bucket = stats.get(fallback) if isinstance(stats.get(fallback), dict) else {}
        if not outreach_bucket_can_do(bucket):
            continue
        if fallback == next_action:
            continue
        params = await pick_outreach_target_params_async(
            db_session,
            settings,
            tenant_id=tenant_id,
            platform=platform,
            account_id=account_id,
            brief=brief,
            state=state,
            action=fallback,
            provider=provider,
        )
        if params:
            return fallback, params, f"优先 {next_action} 无目标，改 {fallback}"

    return None, None, "已入库评论经 LLM 评估后无待触达线索"
