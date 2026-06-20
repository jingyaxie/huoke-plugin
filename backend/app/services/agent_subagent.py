from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.schemas.agent import AgentEvent
from app.services.agent_browser_session import AgentBrowserSession
from app.services.agent_llm import AssistantTurn, stream_chat_completion
from app.services.agent_network_capture import compact_tool_result_for_llm
from app.schemas.agent_profile import AgentProfileOut
from app.services.agent_profile_store import AgentProfileStore
from app.services.agent_run_controller import AgentRunController
from app.services.playwright_tools import TOOL_DEFINITIONS, PlaywrightToolExecutor, parse_tool_arguments

SUBAGENT_PROMPT = """你是浏览器自动化子智能体，在有限步数内完成父智能体分配的单一子任务。
- 使用 browser_* 工具操作页面
- 完成后调用 task_complete 并给出简洁摘要
- 无法完成时调用 task_failed
- 不要调用 spawn_task
- 回复使用中文
"""


def build_subagent_system_prompt(profile: AgentProfileOut | None = None) -> str:
    profile = profile or AgentProfileStore.default_profile()
    parts = [
        "你是浏览器自动化子智能体，在有限步数内完成父智能体分配的单一子任务。",
    ]
    if profile.inherit_base_prompt:
        parts.append(
            "- 使用 browser_* 工具；不要编造未观察到的数据\n"
            "- 登录墙/验证码 → task_failed\n"
            "- 优先复用历史 tool 返回"
        )
        if profile.inherit_workflow_prompt:
            parts.append(
                "- 标准获客档案下：禁止 browser_click/fill 模拟关键词搜索或翻页找评论"
            )
    custom = (profile.system_prompt or "").strip()
    if custom:
        clipped = custom[:1500] + ("…" if len(custom) > 1500 else "")
        parts.append(f"## 父智能体档案约束（{profile.name}）\n{clipped}")
    parts.append(
        "- 完成后 task_complete 并给出简洁摘要\n"
        "- 无法完成时 task_failed\n"
        "- 不要 spawn_task\n"
        "- 回复使用中文"
    )
    return "\n".join(parts)

SUBAGENT_TOOLS = [
    t for t in TOOL_DEFINITIONS if t.get("function", {}).get("name") != "spawn_task"
]


async def run_subagent(
    *,
    task: str,
    session: AgentBrowserSession,
    client: AsyncOpenAI,
    model: str,
    settings_max_steps: int,
    max_steps: int | None = None,
    parent_run_id: str | None = None,
    profile: AgentProfileOut | None = None,
    system_prompt: str | None = None,
) -> AsyncIterator[tuple[AgentEvent, dict[str, Any] | None]]:
    """Yield (event, terminal_result). terminal_result is set only on final done."""
    limit = min(max_steps or settings_max_steps, settings_max_steps)
    prompt = system_prompt or build_subagent_system_prompt(profile)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": task},
    ]
    executor = PlaywrightToolExecutor(session, session.settings)
    controller = AgentRunController.get()
    terminal: dict[str, Any] = {"status": "failed", "summary": "子任务未完成"}

    try:
        for step in range(1, limit + 1):
            if parent_run_id and controller.is_cancelled(parent_run_id):
                terminal = {"status": "cancelled", "summary": "父任务已取消"}
                break

            yield (
                AgentEvent(
                    type="step",
                    data={"step": step, "max_steps": limit, "subagent": True, "task": task[:120]},
                ),
                None,
            )

            turn: AssistantTurn | None = None
            stream_enabled = session.settings.agent_stream_enabled
            async for item in stream_chat_completion(
                client,
                model=model,
                messages=messages,
                tools=SUBAGENT_TOOLS,
                stream=stream_enabled,
            ):
                if isinstance(item, AssistantTurn):
                    turn = item
                else:
                    event = item
                    if event.data is not None:
                        event.data["subagent"] = True
                    yield (event, None)

            if turn is None:
                terminal = {"status": "failed", "summary": "子智能体 LLM 无响应"}
                break

            entry = turn.to_message_entry()
            messages.append(entry)
            tool_calls = turn.tool_calls

            if not tool_calls:
                terminal = {"status": "completed", "summary": turn.content or "子任务完成"}
                break

            for tool_call in tool_calls:
                fn_name = tool_call["function"]["name"]
                fn_args = parse_tool_arguments(tool_call["function"]["arguments"])
                tool_call_id = tool_call["id"]
                yield (
                    AgentEvent(
                        type="tool_start",
                        data={
                            "tool": fn_name,
                            "arguments": fn_args,
                            "tool_call_id": tool_call_id,
                            "subagent": True,
                        },
                    ),
                    None,
                )
                result, _ = await executor.execute(fn_name, fn_args)
                if fn_name == "browser_screenshot" and "base64" in result:
                    result = {**result, "base64_omitted": True}
                    result.pop("base64", None)
                yield (
                    AgentEvent(
                        type="tool_result",
                        data={
                            "tool": fn_name,
                            "tool_call_id": tool_call_id,
                            "result": result,
                            "subagent": True,
                        },
                    ),
                    None,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(compact_tool_result_for_llm(fn_name, result), ensure_ascii=False),
                    }
                )
                if fn_name == "task_complete":
                    terminal = {"status": "completed", "summary": fn_args.get("summary", "")}
                    break
                if fn_name == "task_failed":
                    terminal = {"status": "failed", "summary": fn_args.get("reason", "")}
                    break
            else:
                continue
            break
        else:
            terminal = {"status": "failed", "summary": f"子智能体达到步数上限 ({limit})"}

        done = AgentEvent(
            type="done",
            data={**terminal, "subagent": True, "task": task[:120]},
        )
        yield (done, terminal)
    except Exception as exc:
        yield (AgentEvent(type="error", data={"message": str(exc), "subagent": True}), None)
        terminal = {"status": "failed", "summary": str(exc)}
        yield (
            AgentEvent(type="done", data={**terminal, "subagent": True}),
            terminal,
        )
