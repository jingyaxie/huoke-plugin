"""手动获客（账号主页 / 单条视频）→ Huoke Agent brief 与执行计划。"""
from __future__ import annotations

import re
from typing import Any

from app.services.task_brief_service import TaskBrief
from app.services.supervisor_crawl_helpers import apply_crawl_video_limit_aliases, build_crawl_day_params, show_browser
from app.services.supervisor_outreach import outreach_priority_from_brief

MANUAL_ACQUISITION_MODES = frozenset({"single_video", "account_home"})

_PROFILE_URL_PATTERNS: dict[str, tuple[str, ...]] = {
    "douyin": (r"douyin\.com/user/", r"iesdouyin\.com/share/user/", r"v\.douyin\.com/"),
    "xiaohongshu": (r"xiaohongshu\.com/user/profile/",),
    "kuaishou": (r"kuaishou\.com/profile/", r"v\.kuaishou\.com/"),
}
_VIDEO_URL_PATTERNS: dict[str, tuple[str, ...]] = {
    "douyin": (r"douyin\.com/video/", r"iesdouyin\.com/share/video/"),
    "xiaohongshu": (r"xiaohongshu\.com/explore/", r"xiaohongshu\.com/discovery/item/"),
    "kuaishou": (r"kuaishou\.com/short-video/", r"v\.kuaishou\.com/short"),
}

_OUTREACH_LABELS = {
    "reply": "回复评论",
    "dm": "私信用户",
    "follow": "关注用户",
}


def infer_manual_url_mode(input_url: str, platform: str) -> str | None:
    """根据链接判断手动获客方式；无法判断时返回 None。"""
    raw = str(input_url or "").strip()
    if not raw:
        return None
    plat = str(platform or "douyin").strip().lower()
    profile_hits = any(re.search(pat, raw, re.I) for pat in _PROFILE_URL_PATTERNS.get(plat, ()))
    video_hits = any(re.search(pat, raw, re.I) for pat in _VIDEO_URL_PATTERNS.get(plat, ()))
    if profile_hits and not video_hits:
        return "account_home"
    if video_hits and not profile_hits:
        return "single_video"
    return None


def reconcile_manual_acquisition_mode(mode: str, input_url: str, platform: str) -> str:
    inferred = infer_manual_url_mode(input_url, platform)
    if mode == "account_home":
        return "account_home"
    if mode == "single_video" and inferred == "account_home":
        return "account_home"
    if inferred and inferred in MANUAL_ACQUISITION_MODES:
        return inferred
    return mode if mode in MANUAL_ACQUISITION_MODES else "account_home"


def manual_acquisition_mode(brief: TaskBrief) -> str | None:
    mode = str(brief.goals.get("acquisition_mode") or "").strip().lower()
    if mode in MANUAL_ACQUISITION_MODES:
        return mode
    if brief.goals.get("video_url") or brief.goals.get("input_url") and brief.goals.get("profile_url"):
        return "single_video" if brief.goals.get("video_url") else "account_home"
    return None


def enrich_manual_acquisition_brief(brief: TaskBrief, payload: dict[str, Any] | None) -> TaskBrief:
    if not isinstance(payload, dict):
        return brief

    mode = str(payload.get("acquisition_mode") or "").strip().lower()
    if mode:
        brief.goals["acquisition_mode"] = mode

    input_url = str(payload.get("input_url") or payload.get("video_url") or payload.get("profile_url") or "").strip()
    if input_url:
        brief.goals["input_url"] = input_url
    platform = str(payload.get("platform") or brief.platform or "douyin")
    mode = str(brief.goals.get("acquisition_mode") or mode or "").strip().lower()
    if input_url and mode in MANUAL_ACQUISITION_MODES:
        mode = reconcile_manual_acquisition_mode(mode, input_url, platform)
        brief.goals["acquisition_mode"] = mode
    if mode == "single_video":
        brief.goals["video_url"] = str(payload.get("video_url") or input_url)
    elif mode == "account_home":
        brief.goals["profile_url"] = str(payload.get("profile_url") or input_url)
    elif payload.get("video_url"):
        brief.goals["video_url"] = str(payload.get("video_url"))
    if payload.get("profile_url"):
        brief.goals["profile_url"] = str(payload.get("profile_url"))

    if payload.get("video_publish_days") is not None:
        brief.goals["video_publish_days"] = int(payload.get("video_publish_days"))
    elif payload.get("publish_time_range"):
        from app.services.external_task_service import _map_publish_time_range

        mapped = _map_publish_time_range(payload.get("publish_time_range"))
        if mapped is not None:
            brief.goals["video_publish_days"] = mapped
    if payload.get("comment_days") is not None:
        brief.goals["comment_days"] = int(payload.get("comment_days"))

    crawl_limit = payload.get("crawl_video_limit") or payload.get("max_scan_videos") or payload.get("max_videos")
    if crawl_limit is not None:
        try:
            brief.goals["crawl_video_limit"] = int(crawl_limit)
        except (TypeError, ValueError):
            pass

    brief.goals.setdefault("supervisor_plan_only", True)
    return brief


def _outreach_steps(brief: TaskBrief, *, start_order: int) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    order = start_order
    for action in outreach_priority_from_brief(brief):
        steps.append(
            {
                "id": action,
                "order": order,
                "action": action,
                "label": _OUTREACH_LABELS.get(action, action),
                "status": "pending",
                "required": False,
                "repeat_until": "quota_or_no_targets",
                "params": {},
            }
        )
        order += 1
    return steps


def _resolve_current_index(steps: list[dict[str, Any]]) -> int:
    for idx, step in enumerate(steps):
        if step.get("status") not in {"completed", "skipped"}:
            return idx
    return max(len(steps) - 1, 0)


def build_manual_acquisition_plan(brief: TaskBrief, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    mode = manual_acquisition_mode(brief)
    if not mode:
        return None
    state = state or {}
    target = int(brief.goals.get("target_leads") or 50)
    video_limit = int(brief.goals.get("crawl_video_limit") or 5)
    input_url = str(brief.goals.get("input_url") or brief.goals.get("video_url") or brief.goals.get("profile_url") or "")

    if mode == "single_video":
        crawl_action = "crawl_content_url"
        crawl_label = f"抓取单条视频评论（{input_url[:48]}…）" if len(input_url) > 48 else f"抓取单条视频评论（{input_url}）"
        crawl_params: dict[str, Any] = {
            "video_url": str(brief.goals.get("video_url") or input_url),
            **build_crawl_day_params(brief),
            "show_browser": show_browser(brief),
        }
    else:
        crawl_action = "crawl_profile"
        crawl_label = f"浏览账号主页并抓取评论（{input_url[:48]}…）" if len(input_url) > 48 else f"浏览账号主页并抓取评论（{input_url}）"
        crawl_params = {
            "profile_url": str(brief.goals.get("profile_url") or input_url),
            **build_crawl_day_params(brief),
            "show_browser": show_browser(brief),
        }
        apply_crawl_video_limit_aliases(crawl_params, video_limit)

    outreach_steps = _outreach_steps(brief, start_order=4)
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
            "id": "evaluate",
            "order": 2,
            "action": "evaluate_leads",
            "label": "LLM 评估入库评论是否符合线索标准",
            "status": "completed" if state.get("evaluation_done") else "pending",
            "required": True,
            "params": {"platform": brief.platform or "douyin"},
        },
        {
            "id": "sync_stats",
            "order": 3,
            "action": "query_stats",
            "label": "同步今日 reply/follow/dm 触达配额",
            "status": "completed" if state.get("stats_synced") else "pending",
            "required": True,
            "params": {"platform": brief.platform or "douyin"},
        },
        *outreach_steps,
        {
            "id": "finish",
            "order": 4 + len(outreach_steps),
            "action": "complete",
            "label": f"触达完成后结束（目标线索 ≥ {target or '配置'}）",
            "status": "pending",
            "required": True,
            "params": {},
        },
    ]
    outreach_names = " → ".join(str(s["action"]) for s in outreach_steps) or "无触达"
    summary = (
        f"【{brief.title or '手动获客'}】"
        f" ①{crawl_label} → ②LLM 评估 → ③同步配额 → ④触达（{outreach_names}）→ ⑤结束"
    )
    return {
        "summary": summary,
        "steps": steps,
        "current_index": _resolve_current_index(steps),
        "version": 2,
        "pipeline": f"manual_{mode}",
    }
