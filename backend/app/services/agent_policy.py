from __future__ import annotations

from typing import Any, Literal

from app.schemas.agent_rule import AgentMode, RunMode

READ_ONLY_TOOLS = {
    "browser_get_page_info",
    "browser_get_network_data",
    "browser_get_text",
    "browser_screenshot",
    "browser_wait",
    "list_skills",
    "list_local_comment_files",
    "read_local_comments",
    "analyze_local_comments",
    "query_stored_contents",
    "query_stored_comments",
    "get_stored_content_detail",
    "get_stored_comment",
    "list_task_templates",
}

WRITE_TOOLS = {
    "browser_goto",
    "browser_click",
    "browser_fill",
    "browser_press",
    "browser_scroll",
    "invoke_skill",
}

CONFIRM_TOOLS = {
    "browser_goto",
    "browser_click",
    "browser_fill",
    "browser_press",
    "invoke_skill",
    "spawn_task",
}

CHECKPOINT_TOOLS = WRITE_TOOLS | {"spawn_task"}

SPAWN_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "spawn_task",
        "description": "启动子智能体在独立上下文中执行子任务，完成后仅返回摘要（适合调研、探索等子任务）",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "子任务描述"},
                "max_steps": {
                    "type": "integer",
                    "description": "子智能体最大步数，默认 100",
                },
            },
            "required": ["task"],
        },
    },
}


def is_write_tool(tool_name: str) -> bool:
    return tool_name in CHECKPOINT_TOOLS or tool_name.startswith("skill_")

SUBMIT_PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_plan",
        "description": "提交结构化执行计划，等待用户确认后再执行浏览器操作",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "计划摘要"},
                "steps": {
                    "type": "array",
                    "description": "步骤列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer"},
                            "action": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                        "required": ["step", "action", "detail"],
                    },
                },
            },
            "required": ["summary", "steps"],
        },
    },
}

PLAN_MODE_PROMPT = """
当前为 **Plan 模式**：你只能调研和制定计划，不能直接执行写入类浏览器操作。
- 可用只读工具了解页面：browser_get_page_info、browser_get_network_data、browser_get_text、browser_screenshot、list_skills
- 完成调研后必须调用 submit_plan 提交计划，包含 summary 和 steps
- 不要调用 browser_goto/click/fill 等写入操作
"""

ASK_MODE_PROMPT = """
当前为 **Ask 模式**：只读探索，不能修改页面或执行技能。
- 仅可使用 browser_get_page_info、browser_get_network_data、browser_get_text、browser_screenshot、browser_wait、list_skills
- 不要调用任何写入操作或 invoke_skill
"""


def tool_needs_browser(fn_name: str, *, is_skill: bool = False) -> bool:
    if fn_name in {"task_complete", "task_failed", "list_skills", "submit_plan"}:
        return False
    if fn_name.startswith("browser_") or fn_name == "spawn_subagent":
        return True
    if is_skill or fn_name in {"invoke_skill"} or fn_name.startswith("skill_"):
        return True
    if fn_name.startswith("skillhub_") or fn_name in {"read_skill_resource", "run_skill_script"}:
        return False
    if fn_name in {"list_local_comment_files", "read_local_comments", "analyze_local_comments"}:
        return False
    if fn_name in {"list_task_templates", "create_structured_task"}:
        return False
    return False


def filter_tools_for_mode(
    tools: list[dict[str, Any]],
    mode: AgentMode,
) -> list[dict[str, Any]]:
    if mode == "agent":
        return tools

    allowed = set(READ_ONLY_TOOLS)
    if mode == "plan":
        allowed.add("submit_plan")

    filtered: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("function", {}).get("name", "")
        if name.startswith("skill_") or name in {"task_complete", "task_failed", "invoke_skill"}:
            continue
        if name in allowed:
            filtered.append(tool)

    if mode == "plan" and not any(t.get("function", {}).get("name") == "submit_plan" for t in filtered):
        filtered.append(SUBMIT_PLAN_TOOL)
    return filtered


def requires_approval(
    tool_name: str,
    *,
    run_mode: RunMode,
    mode: AgentMode,
) -> bool:
    if run_mode == "auto" or mode == "ask":
        return False
    if tool_name.startswith("skill_"):
        return True
    return tool_name in CONFIRM_TOOLS
