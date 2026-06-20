from __future__ import annotations

from typing import Any


def build_skillhub_tool_definitions(*, has_packages: bool = True) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "skillhub_search",
                "description": "在 SkillHub 技能注册中心搜索可安装的技能包",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "limit": {"type": "integer", "description": "返回数量上限", "default": 10},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "skillhub_install",
                "description": (
                    "从 SkillHub 安装技能包到当前租户（支持 slug、@namespace/slug、team--slug）。"
                    "安装后可通过 invoke_skill 使用，包内脚本用 run_skill_script，参考资料用 read_skill_resource"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coordinate": {
                            "type": "string",
                            "description": "技能坐标，如 pdf-parser 或 @global/pdf-parser",
                        },
                        "namespace": {"type": "string", "description": "命名空间，默认 global"},
                        "slug": {"type": "string", "description": "技能 slug"},
                        "version": {"type": "string", "description": "可选版本号"},
                        "overwrite": {
                            "type": "boolean",
                            "description": "是否覆盖已安装版本",
                            "default": False,
                        },
                    },
                },
            },
        },
    ]
    if has_packages:
        tools.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "read_skill_resource",
                        "description": (
                            "读取已安装 SkillHub 技能包内的文件（references/、assets/ 或 SKILL.md 补充材料）"
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_id": {"type": "string", "description": "技能 ID"},
                                "path": {
                                    "type": "string",
                                    "description": "相对路径，如 references/guide.md",
                                },
                            },
                            "required": ["skill_id", "path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "run_skill_script",
                        "description": (
                            "执行已安装 SkillHub 技能包 scripts/ 目录下的脚本；"
                            "script 为相对 scripts/ 的路径，如 run.py"
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "skill_id": {"type": "string", "description": "技能 ID"},
                                "script": {"type": "string", "description": "脚本路径，如 run.py"},
                                "args": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "命令行参数",
                                },
                            },
                            "required": ["skill_id", "script"],
                        },
                    },
                },
            ]
        )
    return tools
