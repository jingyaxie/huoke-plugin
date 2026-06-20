"""将编排任务 message（JSON / 自然语言）统一理解为获客 flat payload。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

LEAD_INTENT_HINTS = (
    "获客",
    "线索",
    "抓取",
    "关键词",
    "评论",
    "团餐",
    "配送",
    "target",
    "keyword",
    "lead",
    "crawl",
    "douyin",
    "抖音",
    "小红书",
)

PLATFORM_ALIASES = {
    "douyin": "douyin",
    "抖音": "douyin",
    "xiaohongshu": "xiaohongshu",
    "xhs": "xiaohongshu",
    "小红书": "xiaohongshu",
}


@dataclass
class UnderstoodTaskMessage:
    """理解后的获客任务载荷。"""

    payload: dict[str, Any]
    intent: str | None = None
    source: str = "yingxiaoyi"
    confidence: float = 0.0
    reasoning: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _has_lead_fields(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("keyword")
        or payload.get("product_keyword")
        or payload.get("task_name")
        or payload.get("name")
    )


def _flatten_spec(spec: dict[str, Any], *, outer: dict[str, Any]) -> dict[str, Any]:
    crawl = spec.get("crawl") if isinstance(spec.get("crawl"), dict) else {}
    action_policy = spec.get("action_policy") if isinstance(spec.get("action_policy"), dict) else {}
    daily_limits = spec.get("daily_limits") if isinstance(spec.get("daily_limits"), dict) else {}

    payload: dict[str, Any] = {}
    for key in ("task_name", "keyword", "platform", "region", "account_id"):
        val = spec.get(key)
        if val is not None and val != "":
            payload[key] = val

    if not payload.get("task_name"):
        name = outer.get("name") or outer.get("task_name")
        if name:
            payload["task_name"] = name

    if crawl.get("comment_days") is not None:
        payload["comment_days"] = crawl.get("comment_days")
    if crawl.get("video_publish_days") is not None:
        payload["video_publish_days"] = crawl.get("video_publish_days")
    if crawl.get("target_leads") is not None:
        payload["target_count"] = crawl.get("target_leads")

    for key in ("comment_ratio", "dm_ratio", "follow_ratio", "interval_min_sec", "interval_max_sec"):
        val = action_policy.get(key)
        if val is not None:
            payload[key.replace("_sec", "") if key.endswith("_sec") else key] = val
    if action_policy.get("interval_min_sec") is not None:
        payload["interval_min"] = action_policy.get("interval_min_sec")
    if action_policy.get("interval_max_sec") is not None:
        payload["interval_max"] = action_policy.get("interval_max_sec")

    if daily_limits.get("max_follows") is not None:
        payload["daily_follow_limit"] = daily_limits.get("max_follows")
    if daily_limits.get("max_dms") is not None:
        payload["daily_dm_limit"] = daily_limits.get("max_dms")

    return {k: v for k, v in payload.items() if v is not None and v != ""}


def _unwrap_wrapped_payload(raw: dict[str, Any]) -> tuple[dict[str, Any], str | None, str, dict[str, Any]]:
    intent = raw.get("intent")
    if intent is not None:
        intent = str(intent)

    nested = raw.get("raw_payload")
    if isinstance(nested, dict) and _has_lead_fields(nested):
        return nested, intent, "yingxiaoyi", {"wrapper": "raw_payload"}

    spec = raw.get("spec")
    if isinstance(spec, dict) and _has_lead_fields(spec):
        flat = _flatten_spec(spec, outer=raw)
        template_id = str(raw.get("template_id") or "").strip() or None
        resolved_intent = intent
        if not resolved_intent and template_id == "lead-acquisition":
            resolved_intent = "lead_acquisition"
        return flat, resolved_intent, "task_create_request", {
            "wrapper": "task_create_request",
            "template_id": template_id,
        }

    if _has_lead_fields(raw):
        return raw, intent, "yingxiaoyi", {"wrapper": "flat"}

    return raw, intent, "unknown", {}


def _normalize_platform(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return PLATFORM_ALIASES.get(text.lower()) or PLATFORM_ALIASES.get(text)


def _extract_keyword(text: str) -> str | None:
    patterns = [
        r"关键词[「『\"']([^」』\"']+)[」』\"']",
        r"关键词[:：\s]*([^\s,，;；]+)",
        r"keyword[=:\s]+([^\s,，;；]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_target_count(text: str) -> int | None:
    patterns = [
        r"目标\s*(\d+)\s*条",
        r"目标改[成为]\s*(\d+)\s*条",
        r"改成\s*(\d+)\s*条",
        r"抓取\s*(\d+)\s*条",
        r"(\d+)\s*条线索",
        r"target[_\s-]*(?:count|leads)?[=:\s]+(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _extract_comment_days(text: str) -> int | None:
    patterns = [
        r"近?\s*(\d+)\s*天(?:内)?评论",
        r"评论\s*(\d+)\s*天",
        r"comment[_\s-]*days[=:\s]+(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _extract_platform(text: str) -> str | None:
    lowered = text.lower()
    if "小红书" in text or "xiaohongshu" in lowered or "xhs" in lowered:
        return "xiaohongshu"
    if "抖音" in text or "douyin" in lowered:
        return "douyin"
    return None


def _extract_task_name(text: str) -> str | None:
    match = re.search(r"任务名称[:：\s]+([^\n,，;；]+)", text)
    if match:
        return match.group(1).strip()
    return None


def _extract_region(text: str) -> str | None:
    match = re.search(r"(?:地区|区域)[:：\s]+([^\n,，;；]+)", text)
    if match:
        return match.group(1).strip()
    for city in ("北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安", "重庆", "南京"):
        if city in text:
            return city
    return None


def _looks_like_lead_intent(text: str) -> bool:
    lowered = text.lower()
    return any(hint in text or hint in lowered for hint in LEAD_INTENT_HINTS)


def infer_lead_payload_from_text(text: str) -> UnderstoodTaskMessage | None:
    """从自然语言启发式提取获客字段（同步，无需固定 JSON 模板）。"""
    raw_text = (text or "").strip()
    if not raw_text or raw_text.startswith("{"):
        return None
    if not _looks_like_lead_intent(raw_text):
        return None

    keyword = _extract_keyword(raw_text)
    if not keyword:
        return None

    payload: dict[str, Any] = {"keyword": keyword}
    task_name = _extract_task_name(raw_text)
    if task_name:
        payload["task_name"] = task_name

    platform = _extract_platform(raw_text)
    if platform:
        payload["platform"] = platform

    region = _extract_region(raw_text)
    if region:
        payload["region"] = region

    target = _extract_target_count(raw_text)
    if target is not None:
        payload["target_count"] = target

    comment_days = _extract_comment_days(raw_text)
    if comment_days is not None:
        payload["comment_days"] = comment_days

    confidence = 0.45
    if platform:
        confidence += 0.1
    if target is not None:
        confidence += 0.1
    if comment_days is not None:
        confidence += 0.05
    if region:
        confidence += 0.05

    return UnderstoodTaskMessage(
        payload=payload,
        source="inferred",
        confidence=min(0.85, confidence),
        reasoning="已从自然语言理解获客意图并提取关键字段",
        meta={"input_kind": "natural_language"},
    )


def understand_task_message(message: str) -> UnderstoodTaskMessage | None:
    """统一理解 JSON / 自然语言，返回编排所需的 flat payload。"""
    text = (message or "").strip()
    if not text:
        return None

    if text.startswith("/pipeline-keyword-video-comments"):
        return None

    raw = extract_json_object(text)
    if isinstance(raw, dict):
        payload, intent, source, meta = _unwrap_wrapped_payload(raw)
        if _has_lead_fields(payload):
            template_id = meta.get("template_id")
            if not intent and template_id == "lead-acquisition":
                intent = "lead_acquisition"
            return UnderstoodTaskMessage(
                payload=payload,
                intent=intent,
                source=source,
                confidence=0.9 if source == "task_create_request" else 0.85,
                reasoning="已理解 JSON 结构并提取编排字段"
                + (f"（{meta.get('wrapper')}）" if meta.get("wrapper") else ""),
                meta={**meta, "input_kind": "json"},
            )

    if not raw:
        return infer_lead_payload_from_text(text)

    return None


def is_lead_task_message(message: str) -> bool:
    return understand_task_message(message) is not None
