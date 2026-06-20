from __future__ import annotations

import json
from typing import Any

from app.services.task_brief_service import TaskBrief

# 获客任务默认本地 schema（无 LLM 时回退）
DEFAULT_LEAD_TASK_SCHEMA: dict[str, Any] = {
    "version": 1,
    "description": "获客任务本地台账：线索、触达、抓取批次",
    "tables": [
        {
            "name": "leads",
            "purpose": "匹配后的潜在线索",
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "comment_id", "type": "TEXT"},
                {"name": "content_id", "type": "TEXT"},
                {"name": "content_url", "type": "TEXT"},
                {"name": "nickname", "type": "TEXT"},
                {"name": "comment_text", "type": "TEXT"},
                {"name": "keyword", "type": "TEXT"},
                {"name": "match_score", "type": "REAL", "default": 0},
                {"name": "status", "type": "TEXT", "default": "'new'"},
                {"name": "created_at", "type": "TEXT"},
            ],
        },
        {
            "name": "outreach_events",
            "purpose": "本任务触达记录（评论/私信/关注）",
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "lead_id", "type": "INTEGER"},
                {"name": "action", "type": "TEXT"},
                {"name": "status", "type": "TEXT"},
                {"name": "comment_id", "type": "TEXT"},
                {"name": "target_user_id", "type": "TEXT"},
                {"name": "reply_text", "type": "TEXT"},
                {"name": "error_message", "type": "TEXT"},
                {"name": "created_at", "type": "TEXT"},
            ],
        },
        {
            "name": "crawl_batches",
            "purpose": "关键词抓取批次",
            "columns": [
                {"name": "id", "type": "INTEGER", "primary_key": True},
                {"name": "keyword", "type": "TEXT"},
                {"name": "videos_processed", "type": "INTEGER", "default": 0},
                {"name": "comments_captured", "type": "INTEGER", "default": 0},
                {"name": "status", "type": "TEXT"},
                {"name": "created_at", "type": "TEXT"},
            ],
        },
        {
            "name": "task_kv",
            "purpose": "任务级键值状态（进度、计数器）",
            "columns": [
                {"name": "key", "type": "TEXT", "primary_key": True},
                {"name": "value", "type": "TEXT"},
                {"name": "updated_at", "type": "TEXT"},
            ],
        },
    ],
}

DEFAULT_HELPER_CODE = '''"""任务沙盒辅助逻辑 — 由编排自动生成，可按业务扩展。"""

from __future__ import annotations

from typing import Any


def match_comment(comment_text: str, keywords: list[str], exclude: list[str] | None = None) -> bool:
    """简单关键词匹配，过滤招聘/广告等噪声。"""
    text = (comment_text or "").strip()
    if not text:
        return False
    exclude = exclude or []
    for word in exclude:
        if word and word in text:
            return False
    if not keywords:
        return True
    return any(k and k in text for k in keywords)


def next_outreach_action(
    stats: dict[str, Any],
    priority: list[str] | None = None,
) -> str | None:
    """根据配额选择下一触达方式。priority 默认 reply → dm → follow。"""
    order = priority or ["reply", "dm", "follow"]
    for action in order:
        bucket = stats.get(action) if isinstance(stats.get(action), dict) else {}
        if bucket.get("can_do"):
            return action
    return None
'''


async def design_task_schema(
    brief: TaskBrief,
    message: str,
    *,
    settings: Any,
    provider: str = "deepseek",
) -> dict[str, Any]:
    """LLM 根据简报设计任务本地 schema；失败则回退默认。"""
    from app.services.ai_client import AIClientFactory
    from app.services.agent_llm import resolve_default_provider

    factory = AIClientFactory(settings)
    client = factory.llm_client()
    if client is None:
        return dict(DEFAULT_LEAD_TASK_SCHEMA)

    model = factory.llm_model()
    system = (
        "你是任务数据架构师。为单个获客任务设计本地 SQLite schema（仅本任务沙盒）。"
        "输出 JSON：version(int), description(string), tables(array)。"
        "每个 table：name, purpose, columns(array of {name,type,primary_key?,default?})。"
        "必须含 leads、outreach_events、crawl_batches 三张表；可追加业务表。"
        "type 仅允许 INTEGER|TEXT|REAL。不要 SQL 语句。"
    )
    user = json.dumps(
        {
            "title": brief.title,
            "goals": brief.goals,
            "constraints": brief.constraints,
            "success_criteria": brief.success_criteria,
            "user_message": (message or "")[:3000],
            "default_schema": DEFAULT_LEAD_TASK_SCHEMA,
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
        if isinstance(data, dict) and isinstance(data.get("tables"), list) and data["tables"]:
            data.setdefault("version", 1)
            return data
    except Exception:
        pass
    return dict(DEFAULT_LEAD_TASK_SCHEMA)
