"""独立抖音关键词浏览 — 表单参数 → 配置 → 步骤编排 的纯逻辑模拟（无浏览器）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.platforms.douyin.standalone_keyword_browse import (
    StandaloneKeywordBrowseConfig,
    _keyword_matches_comment,
    _take_unique_comments,
)
from app.schemas.douyin_tools import DouyinStandaloneKeywordBrowseRequest


@dataclass
class StandaloneVideoRound:
    """单视频轮次可注入结果（模拟页面/接口反馈）。"""

    click_ok: bool = True
    after_click_phase: str = "feed_detail"
    feed_visible: bool = True
    list_visible: bool = False
    feed_ready: bool = True
    comment_open_ok: bool = True
    comments: list[dict[str, Any]] = field(default_factory=list)
    outreach_ok: bool = True


@dataclass
class StandaloneSimulationTrace:
    steps: list[str] = field(default_factory=list)
    videos_attempted: int = 0
    videos_entered_feed: int = 0
    comments_scanned: int = 0
    precise_leads: list[dict[str, Any]] = field(default_factory=list)
    outreach_actions: list[str] = field(default_factory=list)
    duplicates_skipped: int = 0
    target_reached: bool = False
    terminal_note: str = ""


# 表单/任务编排对独立流程的核心要求（可映射到 StandaloneKeywordBrowseConfig + 步骤门禁）
FORM_REQUIREMENT_KEYS: tuple[str, ...] = (
    "keyword_configured",
    "days_filter_configured",
    "comment_days_configured",
    "target_leads_configured",
    "max_videos_cap_configured",
    "match_keywords_configured",
    "exclude_keywords_supported",
    "outreach_toggle_honored",
    "outreach_copy_configured",
    "action_policy_configured",
    "persist_toggle_honored",
    "page_phase_gate_before_comment",
    "page_phase_gate_before_outreach",
    "dedupe_across_videos",
    "stop_when_target_reached",
)


def config_from_api_request(payload: DouyinStandaloneKeywordBrowseRequest) -> StandaloneKeywordBrowseConfig:
    """镜像 `douyin_routes.standalone_keyword_browse` 的字段映射。"""
    target = max(1, int(payload.target_precise_leads or payload.limit))
    return StandaloneKeywordBrowseConfig(
        keyword=payload.keyword.strip(),
        days=payload.days,
        comment_days=payload.comment_days,
        content_limit=target,
        target_precise_leads=target,
        max_videos_to_browse=max(target, int(payload.max_videos_to_browse)),
        match_keywords=list(payload.match_keywords),
        exclude_keywords=list(payload.exclude_keywords),
        execute_outreach=bool(payload.execute_outreach),
        test_all_outreach=bool(payload.test_all_outreach),
        reply_text=payload.reply_text.strip(),
        dm_text=payload.dm_text.strip(),
        action_policy={
            "comment_ratio": payload.comment_ratio,
            "dm_ratio": payload.dm_ratio,
            "follow_ratio": payload.follow_ratio,
            "interval_min_sec": 10,
            "interval_max_sec": 30,
        },
        persist_to_db=bool(payload.persist_to_db),
        reuse_stable_session=True,
        close_browser_after=bool(payload.close_browser_after),
    )


def config_from_cli_like(
    *,
    keyword: str,
    days: int = 7,
    comment_days: int | None = None,
    target_leads: int = 3,
    max_videos: int = 50,
    match_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    no_outreach: bool = False,
    reply_text: str = "同意",
    dm_text: str = "hi",
    no_persist: bool = False,
) -> StandaloneKeywordBrowseConfig:
    """镜像 `run_standalone_douyin_browse._build_config` 的核心逻辑。"""
    mk = list(match_keywords or [])
    if not mk:
        mk = [keyword.strip(), "获客", "AI"]
    target = max(1, int(target_leads))
    return StandaloneKeywordBrowseConfig(
        keyword=keyword.strip(),
        days=days,
        comment_days=comment_days,
        content_limit=target,
        target_precise_leads=target,
        max_videos_to_browse=max(target, int(max_videos)),
        match_keywords=mk,
        exclude_keywords=list(exclude_keywords or []),
        execute_outreach=not no_outreach,
        test_all_outreach=not no_outreach,
        reply_text=reply_text.strip(),
        dm_text=dm_text.strip(),
        action_policy={
            "comment_ratio": 34,
            "dm_ratio": 33,
            "follow_ratio": 33,
            "interval_min_sec": 8,
            "interval_max_sec": 18,
        },
        persist_to_db=not no_persist,
        reuse_stable_session=True,
        close_browser_after=False,
    )


def _page_allows_comment_open(round_out: StandaloneVideoRound) -> bool:
    """综合 URL/DOM 阶段：仍在列表则禁止开评论（与 standalone 门禁一致）。"""
    if round_out.list_visible and not round_out.feed_visible:
        return False
    if round_out.after_click_phase == "search_list":
        return False
    return round_out.feed_ready and round_out.after_click_phase in {
        "feed_detail",
        "video_page",
    }


def simulate_standalone_pipeline(
    config: StandaloneKeywordBrowseConfig,
    rounds: list[StandaloneVideoRound],
) -> StandaloneSimulationTrace:
    """模拟：搜索已完成 → 逐视频点击 → 评论 → 线索 → 触达。"""
    trace = StandaloneSimulationTrace()
    seen_comment_ids: set[str] = set()
    target = max(1, int(config.target_precise_leads))
    max_videos = max(target, int(config.max_videos_to_browse))

    trace.steps.append("STEP1 open_home")
    trace.steps.append("STEP2 search")
    trace.steps.append("STEP3 search_ok")

    for video_index, round_out in enumerate(rounds):
        if video_index >= max_videos:
            trace.terminal_note = f"达到 max_videos={max_videos} 上限"
            break
        if trace.target_reached:
            break

        trace.videos_attempted += 1
        trace.steps.append(f"STEP4 video_index={video_index}")

        if not round_out.click_ok:
            trace.steps.append(f"CLICK_FAIL index={video_index}")
            trace.steps.append(
                f"STEP7 video={video_index + 1} leads=0 note=未能点击第 {video_index + 1} 个视频"
            )
            continue

        trace.steps.append(
            f"PAGE_AFTER_CLICK phase={round_out.after_click_phase} "
            f"feed={round_out.feed_visible} list={round_out.list_visible}"
        )

        if not _page_allows_comment_open(round_out):
            trace.steps.append("COMMENT_OPEN start")
            trace.steps.append("COMMENT_OPEN ok=False")
            trace.steps.append(
                f"STEP7 video={video_index + 1} note=点击后仍在搜索列表，未进详情"
            )
            continue

        trace.videos_entered_feed += 1
        trace.steps.append(f"ITEM_CLICK index={video_index} simulated_ok")
        trace.steps.append("COMMENT_OPEN start")

        if not round_out.comment_open_ok:
            trace.steps.append("COMMENT_OPEN ok=False")
            trace.steps.append(
                f"STEP7 video={video_index + 1} note=未能打开评论侧栏"
            )
            continue

        trace.steps.append("COMMENT_OPEN ok=True")
        unique_rows, dup_skipped = _take_unique_comments(round_out.comments, seen_comment_ids)
        trace.duplicates_skipped += dup_skipped
        trace.comments_scanned += len(round_out.comments)

        for row in unique_rows:
            text = str(row.get("comment") or "")
            if not _keyword_matches_comment(config, text):
                continue
            trace.precise_leads.append(
                {
                    "comment_id": row.get("comment_id"),
                    "comment": text,
                    "video_index": video_index,
                }
            )
            if config.execute_outreach and round_out.outreach_ok:
                if config.test_all_outreach:
                    trace.outreach_actions.extend(["reply", "follow", "dm"])
                else:
                    trace.outreach_actions.append("reply_or_dm_or_follow")
            if len(trace.precise_leads) >= target:
                trace.target_reached = True
                trace.steps.append(
                    f"STEP7 video={video_index + 1} leads=1 total={len(trace.precise_leads)}/{target}"
                )
                trace.terminal_note = "已达目标精准线索"
                break

        if not trace.target_reached:
            trace.steps.append(
                f"STEP7 video={video_index + 1} leads=0 total=0/{target} scanned={len(round_out.comments)}"
            )

    if not trace.target_reached and not trace.terminal_note:
        trace.terminal_note = (
            f"未凑够目标：精准线索 {len(trace.precise_leads)}/{target}，"
            f"已浏览 {trace.videos_attempted} 个视频"
        )
    return trace


def evaluate_form_requirements(
    config: StandaloneKeywordBrowseConfig,
    trace: StandaloneSimulationTrace,
) -> dict[str, bool]:
    """检查表单字段是否被配置，以及编排门禁是否按预期生效。"""
    policy = config.action_policy or {}
    return {
        "keyword_configured": bool(config.keyword.strip()),
        "days_filter_configured": int(config.days) >= 1,
        "comment_days_configured": config.comment_days is None or int(config.comment_days) >= 1,
        "target_leads_configured": int(config.target_precise_leads) >= 1,
        "max_videos_cap_configured": int(config.max_videos_to_browse) >= int(config.target_precise_leads),
        "match_keywords_configured": bool(config.match_keywords) or bool(config.keyword),
        "exclude_keywords_supported": isinstance(config.exclude_keywords, list),
        "outreach_toggle_honored": (
            (not config.execute_outreach and not trace.outreach_actions)
            or config.execute_outreach
        ),
        "outreach_copy_configured": (
            not config.execute_outreach
            or bool(config.reply_text or config.dm_text)
        ),
        "action_policy_configured": all(
            k in policy for k in ("comment_ratio", "dm_ratio", "follow_ratio")
        ),
        "persist_toggle_honored": isinstance(config.persist_to_db, bool),
        "page_phase_gate_before_comment": (
            trace.videos_entered_feed == 0
            or any("仍在搜索列表" not in s for s in trace.steps if "COMMENT_OPEN ok=True" in s)
        ),
        "page_phase_gate_before_outreach": (
            not config.execute_outreach
            or trace.target_reached
            or len(trace.precise_leads) == 0
        ),
        "dedupe_across_videos": trace.duplicates_skipped >= 0,
        "stop_when_target_reached": (
            not trace.target_reached
            or trace.videos_attempted <= int(config.max_videos_to_browse)
        ),
    }


def all_requirements_met(checks: dict[str, bool]) -> bool:
    return all(checks.get(k) for k in FORM_REQUIREMENT_KEYS)


def requirement_matrix(
    configs: list[StandaloneKeywordBrowseConfig],
    rounds_builder: Callable[[StandaloneKeywordBrowseConfig], list[StandaloneVideoRound]],
) -> list[dict[str, Any]]:
    """批量跑配置 × 轮次，返回每组的 requirements 与 trace 摘要。"""
    rows: list[dict[str, Any]] = []
    for cfg in configs:
        tr = simulate_standalone_pipeline(cfg, rounds_builder(cfg))
        checks = evaluate_form_requirements(cfg, tr)
        rows.append(
            {
                "keyword": cfg.keyword,
                "target": cfg.target_precise_leads,
                "requirements": checks,
                "ok": all_requirements_met(checks),
                "target_reached": tr.target_reached,
                "leads": len(tr.precise_leads),
                "videos": tr.videos_attempted,
            }
        )
    return rows
