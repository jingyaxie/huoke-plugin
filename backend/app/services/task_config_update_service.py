from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.services.agent_llm import resolve_default_provider
from app.services.ai_client import AIClientFactory
from app.services.message_payload_normalizer import (
    _extract_comment_days,
    _extract_keyword,
    _extract_platform,
    _extract_region,
    _extract_target_count,
    _extract_task_name,
    extract_json_object,
    understand_task_message,
)
from app.services.task_brief_service import TaskBrief, _finalize_brief
from app.services.task_skill_playbook import skill_catalog_for_llm

CRAWL_VIDEO_LIMIT_KEYS = ("crawl_video_limit", "video_limit", "content_limit", "limit", "video_limit_per_batch")

OUTREACH_PRIORITY_ALIASES = {
    "私信": "dm",
    "评论": "reply",
    "回复": "reply",
    "关注": "follow",
    "dm": "dm",
    "reply": "reply",
    "follow": "follow",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def payload_to_brief_patch(payload: dict[str, Any]) -> dict[str, Any]:
    """将 flat 获客 payload 转为 TaskBrief 字段 patch。"""
    patch: dict[str, Any] = {}
    for key in ("keyword", "platform", "region", "success_criteria"):
        val = payload.get(key)
        if val is not None and val != "":
            patch[key] = val

    task_name = payload.get("task_name") or payload.get("name")
    if task_name:
        patch["title"] = str(task_name)

    goals: dict[str, Any] = {}
    for src in ("target_count", "target_leads", "requested_target"):
        if payload.get(src) is not None:
            goals["target_leads"] = int(payload[src])
            break
    if payload.get("repeat_mode") is not None:
        goals["repeat_mode"] = str(payload["repeat_mode"])
    for key in ("round_target_count", "round_target_leads", "max_rounds"):
        if payload.get(key) is not None:
            goals[key] = int(payload[key])
    if payload.get("comment_days") is not None:
        goals["comment_days"] = int(payload["comment_days"])
    if payload.get("video_publish_days") is not None:
        goals["video_publish_days"] = int(payload["video_publish_days"])
    for key in CRAWL_VIDEO_LIMIT_KEYS:
        if payload.get(key) is not None:
            goals["crawl_video_limit"] = int(payload[key])
            break
    if goals:
        patch["goals"] = goals

    constraints: dict[str, Any] = {}
    for src, dst in (
        ("daily_reply_limit", "daily_reply_limit"),
        ("daily_follow_limit", "daily_follow_limit"),
        ("daily_dm_limit", "daily_dm_limit"),
        ("match_keywords", "match_keywords"),
        ("exclude_keywords", "exclude_keywords"),
        ("outreach_priority", "outreach_priority"),
        ("repeat_mode", "repeat_mode"),
        ("round_target_count", "round_target_count"),
        ("round_target_leads", "round_target_leads"),
        ("max_rounds", "max_rounds"),
        ("reply_templates", "reply_templates"),
        ("dm_templates", "dm_templates"),
        ("reply_template", "reply_template"),
        ("dm_template", "dm_template"),
    ):
        val = payload.get(src)
        if val is not None and val != "":
            constraints[dst] = int(val) if dst in {"round_target_count", "round_target_leads", "max_rounds"} else val
    if constraints:
        patch["constraints"] = constraints

    return patch


def extract_structured_patch(instruction: str) -> dict[str, Any] | None:
    """从 JSON 字符串或嵌套 spec 提取配置 patch。"""
    text = (instruction or "").strip()
    if not text:
        return None

    raw = extract_json_object(text)
    if not isinstance(raw, dict):
        return None

    nested = raw.get("config")
    if isinstance(nested, dict):
        return nested

    brief_native_keys = {
        "title",
        "keyword",
        "platform",
        "region",
        "goals",
        "constraints",
        "success_criteria",
        "brief_md",
    }
    if any(key in raw for key in ("goals", "constraints", "brief_md")):
        return {k: v for k, v in raw.items() if k in brief_native_keys}

    understood = understand_task_message(text)
    if understood and isinstance(understood.payload, dict):
        return payload_to_brief_patch(understood.payload)

    flat_patch = payload_to_brief_patch(raw)
    native_patch = {k: v for k, v in raw.items() if k in brief_native_keys}
    if flat_patch or native_patch:
        return _deep_merge_dict(flat_patch, native_patch)

    return None


def apply_rule_based_nl_patch(brief: TaskBrief, text: str) -> tuple[TaskBrief, list[str]]:
    """自然语言启发式补丁（无需 LLM）。"""
    changes: list[str] = []
    updated = brief.model_copy(deep=True)
    raw = (text or "").strip()
    if not raw:
        return updated, changes

    keyword = _extract_keyword(raw)
    if keyword:
        updated.keyword = keyword
        changes.append(f"关键词 → {keyword}")

    task_name = _extract_task_name(raw)
    if task_name:
        updated.title = task_name
        changes.append(f"任务名称 → {task_name}")

    platform = _extract_platform(raw)
    if platform:
        updated.platform = platform
        changes.append(f"平台 → {platform}")

    region = _extract_region(raw)
    if region:
        updated.region = region
        changes.append(f"地区 → {region}")

    target = _extract_target_count(raw)
    if target is not None:
        updated.goals = {**updated.goals, "target_leads": target}
        changes.append(f"目标线索数 → {target}")
    for pattern in (r"(?:视频数|视频上限|抓取视频|抓)\s*(\d+)\s*个?视频", r"crawl_video_limit\s*[=:]\s*(\d+)"):
        import re

        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            updated.goals = {**updated.goals, "crawl_video_limit": int(match.group(1))}
            changes.append(f"每批抓取视频数 → {match.group(1)}")
            break

    comment_days = _extract_comment_days(raw)
    if comment_days is not None:
        updated.goals = {**updated.goals, "comment_days": comment_days}
        changes.append(f"评论抓取天数 → {comment_days}")

    if "私信优先" in raw or "优先私信" in raw:
        updated.constraints = {
            **updated.constraints,
            "outreach_priority": ["dm", "reply", "follow"],
        }
        changes.append("触达优先级 → 私信优先")
    elif "评论优先" in raw or "优先评论" in raw or "回复优先" in raw:
        updated.constraints = {
            **updated.constraints,
            "outreach_priority": ["reply", "dm", "follow"],
        }
        changes.append("触达优先级 → 评论优先")
    elif "关注优先" in raw:
        updated.constraints = {
            **updated.constraints,
            "outreach_priority": ["follow", "reply", "dm"],
        }
        changes.append("触达优先级 → 关注优先")

    for limit_key, patterns in (
        ("daily_reply_limit", (r"评论上限\s*(\d+)", r"回复上限\s*(\d+)", r"daily_reply_limit\s*[=:]\s*(\d+)")),
        ("daily_dm_limit", (r"私信上限\s*(\d+)", r"daily_dm_limit\s*[=:]\s*(\d+)")),
        ("daily_follow_limit", (r"关注上限\s*(\d+)", r"daily_follow_limit\s*[=:]\s*(\d+)")),
    ):
        import re

        for pattern in patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if match:
                updated.constraints = {**updated.constraints, limit_key: int(match.group(1))}
                changes.append(f"{limit_key} → {match.group(1)}")
                break

    return updated, changes


def apply_patch_to_brief(brief: TaskBrief, patch: dict[str, Any]) -> TaskBrief:
    data = brief.model_dump()
    for key, value in patch.items():
        if key in {"goals", "constraints"} and isinstance(value, dict):
            data[key] = _deep_merge_dict(data.get(key) or {}, value)
        elif value is not None:
            data[key] = value
    return TaskBrief.model_validate(data)


async def _llm_patch_brief(
    brief: TaskBrief,
    instruction: str,
    *,
    settings: Settings,
    tenant_id: str,
    provider: str,
) -> TaskBrief:
    factory = AIClientFactory(settings)
    client = factory.llm_client()
    if client is None:
        patched, _ = apply_rule_based_nl_patch(brief, instruction)
        return patched

    model = factory.llm_model()
    system = (
        "你是任务配置编辑助手。根据当前任务简报与用户修改指令，输出更新后的完整配置 JSON。"
        "只输出 JSON，字段：title, brief_md, platform, keyword, region, goals, constraints, "
        "success_criteria, reasoning, confidence。"
        "仅修改用户明确要求的部分，其余保留。brief_md 须为完整 Markdown。"
        "Supervisor 只能使用 skill_catalog 中的动作。"
    )
    user = json.dumps(
        {
            "tenant_id": tenant_id,
            "current_brief": brief.model_dump(),
            "user_instruction": instruction,
            "skill_catalog": skill_catalog_for_llm(brief.platform or "douyin"),
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
        if isinstance(data, dict):
            merged = apply_patch_to_brief(brief, data)
            merged.reasoning = str(data.get("reasoning") or f"配置已按指令更新：{instruction[:200]}")
            merged.llm_available = True
            merged.llm_fallback = False
            merged.confidence = float(data.get("confidence") or 0.75)
            return merged
    except Exception:
        pass
    patched, _ = apply_rule_based_nl_patch(brief, instruction)
    return patched


def brief_to_job_message(brief: TaskBrief) -> str:
    """将简报核心字段序列化为 job.message（便于后续再编辑）。"""
    payload = {
        "task_name": brief.title,
        "keyword": brief.keyword,
        "platform": brief.platform,
        "region": brief.region,
        "target_count": brief.goals.get("target_leads"),
        "repeat_mode": brief.goals.get("repeat_mode") or brief.constraints.get("repeat_mode"),
        "round_target_count": brief.goals.get("round_target_count") or brief.constraints.get("round_target_count"),
        "max_rounds": brief.goals.get("max_rounds") or brief.constraints.get("max_rounds"),
        "comment_days": brief.goals.get("comment_days"),
        "crawl_video_limit": brief.goals.get("crawl_video_limit"),
        "constraints": brief.constraints,
        "success_criteria": brief.success_criteria,
    }
    return json.dumps(
        {k: v for k, v in payload.items() if v is not None and v != ""},
        ensure_ascii=False,
        indent=2,
    )


async def update_task_config(
    current: TaskBrief,
    *,
    instruction: str = "",
    config: dict[str, Any] | None = None,
    settings: Settings,
    tenant_id: str,
    provider: str = "deepseek",
) -> tuple[TaskBrief, dict[str, Any]]:
    """用自然语言或 JSON 更新任务配置，返回新简报与变更元数据。"""
    changes: list[str] = []
    updated = current.model_copy(deep=True)

    if config:
        patch = _deep_merge_dict(payload_to_brief_patch(config), config)
        updated = apply_patch_to_brief(updated, patch)
        changes.append("structured_config_patch")

    text = (instruction or "").strip()
    if text:
        structured = extract_structured_patch(text)
        if structured:
            updated = apply_patch_to_brief(updated, structured)
            changes.append("json_instruction_patch")
        else:
            rule_patched, rule_changes = apply_rule_based_nl_patch(updated, text)
            if rule_changes:
                updated = rule_patched
                changes.extend(rule_changes)
            else:
                updated = await _llm_patch_brief(
                    updated,
                    text,
                    settings=settings,
                    tenant_id=tenant_id,
                    provider=provider,
                )
                changes.append("llm_instruction_patch")

    updated = _finalize_brief(updated, agent_strategy=updated.agent_strategy)
    if not updated.brief_md.strip():
        updated.brief_md = current.brief_md

    meta = {
        "at": _utc_now_iso(),
        "changes": changes,
        "instruction_preview": text[:500] if text else "",
        "had_structured_config": bool(config),
    }
    return updated, meta
