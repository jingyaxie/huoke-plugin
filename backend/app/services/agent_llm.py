from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from app.core.config import Settings
from app.schemas.agent import AgentEvent

COMPRESS_SYSTEM_PROMPT = """你是上下文压缩助手。将给定对话历史压缩为简洁中文摘要。
保留：用户目标、已完成关键步骤、页面/URL 状态、工具结果要点、失败原因、待定事项、可复用的结构化线索（如ID/URL/作者/关键词）。
省略：重复尝试、冗长 JSON、截图占位说明。控制在 800 字以内。"""

DEEPSEEK_SCREENSHOT_HINT = (
    "【页面截图已生成并显示在用户界面】DeepSeek 不支持图像输入。"
    "请使用 browser_get_text 或 browser_get_page_info 获取页面文字与 URL 后继续任务。"
)


def repair_messages_tool_responses(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """规范 tool 消息序列：assistant(tool_calls) 后必须紧跟 tool 响应，移除孤儿 tool。"""
    repaired: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")

        if role == "tool":
            i += 1
            continue

        if role != "assistant" or not msg.get("tool_calls"):
            repaired.append(msg)
            i += 1
            continue

        tool_calls = msg["tool_calls"]
        content = msg.get("content")
        repaired.append(
            {
                **msg,
                "content": content if content else None,
                "tool_calls": tool_calls,
            }
        )
        i += 1

        expected_ids = [tc["id"] for tc in tool_calls if tc.get("id")]
        collected: dict[str, dict[str, Any]] = {}
        interleaved: list[dict[str, Any]] = []

        while i < len(messages) and len(collected) < len(expected_ids):
            cur = messages[i]
            cur_role = cur.get("role")
            if cur_role == "tool":
                tid = cur.get("tool_call_id")
                if tid in expected_ids and tid not in collected:
                    collected[tid] = cur
                i += 1
                continue
            if cur_role == "user":
                interleaved.append(cur)
                i += 1
                continue
            break

        for tid in expected_ids:
            if tid in collected:
                repaired.append(collected[tid])
            else:
                repaired.append(
                    {
                        "role": "tool",
                        "tool_call_id": tid,
                        "content": json.dumps(
                            {"error": "工具未执行或已跳过"},
                            ensure_ascii=False,
                        ),
                    }
                )

        repaired.extend(interleaved)
    return repaired


def trim_assistant_tool_call(
    messages: list[dict[str, Any]],
    history: list[dict[str, Any]],
    tool_call_id: str,
) -> list[dict[str, Any]]:
    """审批暂停时仅保留当前 tool_call，其余延后执行。"""
    if not messages or messages[-1].get("role") != "assistant":
        return []
    entry = messages[-1]
    all_calls = entry.get("tool_calls") or []
    current = [tc for tc in all_calls if tc.get("id") == tool_call_id]
    deferred = [tc for tc in all_calls if tc.get("id") != tool_call_id]
    if current:
        trimmed = {**entry, "tool_calls": current}
        messages[-1] = trimmed
        if history and history[-1].get("role") == "assistant":
            history[-1] = trimmed
    return deferred


def prepare_messages_for_provider(
    messages: list[dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    """DeepSeek 不支持 Vision；将 multimodal 消息转为纯文本。"""
    if provider != "deepseek":
        return messages
    prepared: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            prepared.append(msg)
            continue
        text_parts: list[str] = []
        has_image = False
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and part.get("text"):
                text_parts.append(str(part["text"]))
            elif part.get("type") == "image_url":
                has_image = True
        if has_image:
            text_parts.append(DEEPSEEK_SCREENSHOT_HINT)
        prepared.append({**msg, "content": "\n".join(text_parts) if text_parts else DEEPSEEK_SCREENSHOT_HINT})
    return prepared


def resolve_default_provider(settings: Settings) -> str:
    return "deepseek"


@dataclass
class AssistantTurn:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_message_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": self.content if self.content else None,
        }
        if self.tool_calls:
            entry["tool_calls"] = self.tool_calls
        return entry


def _merge_tool_call_delta(
    accumulated: dict[int, dict[str, str]],
    delta_tool_calls: list[Any],
) -> None:
    for tc in delta_tool_calls:
        idx = tc.index
        if idx not in accumulated:
            accumulated[idx] = {"id": "", "name": "", "arguments": ""}
        if tc.id:
            accumulated[idx]["id"] = tc.id
        if tc.function:
            if tc.function.name:
                accumulated[idx]["name"] = tc.function.name
            if tc.function.arguments:
                accumulated[idx]["arguments"] += tc.function.arguments


def _tool_calls_from_accumulated(accumulated: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
    if not accumulated:
        return []
    return [
        {
            "id": item["id"],
            "type": "function",
            "function": {
                "name": item["name"],
                "arguments": item["arguments"],
            },
        }
        for _, item in sorted(accumulated.items())
    ]


async def stream_chat_completion(
    client: AsyncOpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    stream: bool = True,
) -> AsyncIterator[AgentEvent | AssistantTurn]:
    """Yield AgentEvent deltas during streaming; final item is AssistantTurn."""
    if not stream:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto" if tools else None,
        )
        message = response.choices[0].message
        tool_calls = []
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        content = message.content or ""
        if content:
            yield AgentEvent(
                type="message",
                data={"role": "assistant", "content": content, "final": True},
            )
        yield AssistantTurn(content=content, tool_calls=tool_calls)
        return

    content_parts: list[str] = []
    tool_acc: dict[int, dict[str, str]] = {}
    stream_resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto" if tools else None,
        stream=True,
    )
    async for chunk in stream_resp:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            content_parts.append(delta.content)
            yield AgentEvent(
                type="message_delta",
                data={"delta": delta.content, "role": "assistant"},
            )
        if delta.tool_calls:
            _merge_tool_call_delta(tool_acc, delta.tool_calls)

    content = "".join(content_parts)
    tool_calls = _tool_calls_from_accumulated(tool_acc)
    if content or tool_calls:
        yield AgentEvent(
            type="message",
            data={
                "role": "assistant",
                "content": content,
                "final": True,
                "has_tool_calls": bool(tool_calls),
            },
        )
    yield AssistantTurn(content=content, tool_calls=tool_calls)


def _format_history_for_compress(history: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in history:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = " ".join(text_parts)
        if role == "assistant" and msg.get("tool_calls"):
            names = [
                tc.get("function", {}).get("name", "")
                for tc in msg.get("tool_calls", [])
            ]
            lines.append(f"assistant: [调用工具 {', '.join(names)}] {content}")
        elif role == "tool":
            raw = str(content)
            if len(raw) > 500:
                raw = raw[:500] + "..."
            lines.append(f"tool: {raw}")
        else:
            text = str(content)
            if len(text) > 2000:
                text = text[:2000] + "..."
            lines.append(f"{role}: {text}")
    return "\n\n".join(lines)


async def maybe_compress_history(
    history: list[dict[str, Any]],
    *,
    client: AsyncOpenAI,
    model: str,
    settings: Settings,
) -> tuple[list[dict[str, Any]], AgentEvent | None]:
    if not settings.agent_compress_enabled:
        return history, None

    threshold = settings.agent_compress_threshold_messages
    keep = settings.agent_compress_keep_recent
    if len(history) <= threshold:
        return history, None

    existing_summary_idx = None
    for i, msg in enumerate(history):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            if msg["content"].startswith("【对话历史摘要】"):
                existing_summary_idx = i
                break

    compress_end = len(history) - keep
    if compress_end <= 0:
        return history, None

    if existing_summary_idx is not None and existing_summary_idx >= compress_end - 1:
        return history, None

    to_compress = history[:compress_end]
    recent = history[compress_end:]
    transcript = _format_history_for_compress(to_compress)
    if not transcript.strip():
        return history, None

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": COMPRESS_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
    )
    summary = (response.choices[0].message.content or "").strip()
    if not summary:
        return history, None

    compressed = [
        {"role": "user", "content": f"【对话历史摘要】\n{summary}"},
        *recent,
    ]
    event = AgentEvent(
        type="context_compressed",
        data={
            "before": len(history),
            "after": len(compressed),
            "summary_length": len(summary),
        },
    )
    return compressed, event
