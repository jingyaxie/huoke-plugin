from __future__ import annotations

from typing import Any

COMMENT_DATA_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_local_comment_files",
            "description": (
                "列出磁盘上的评论 JSON 文件（/app/reports/comments_*.json），不是 MySQL 数据库。"
                "用户要求「从数据库查」时请用 query_stored_comments；本工具仅用于分析本地导出文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少个文件，默认 20",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_local_comments",
            "description": (
                "从本地已下载的评论 JSON 读取数据（file_name 为文件名或 output_file 路径）。"
                "用于查看、汇总评论内容；勿为此目的再次调用 crawl-video-comments。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "文件名如 comments_douyin_default_xxx.json，或工具返回的 output_file 路径",
                    },
                    "max_comments": {
                        "type": "integer",
                        "description": "最多返回条数，默认 200",
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_local_comments",
            "description": (
                "从本地评论 JSON 筛选有意向用户（询价、预约、本地安装、留联系方式等）。"
                "默认分析对话中最近抓取产生的文件；可指定 file_names。不访问网页。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，指定一个或多个评论文件名；为空则用对话中最近的 output_file",
                    },
                    "intent_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，额外意向关键词，如「淋浴房」「安装」",
                    },
                    "max_leads": {
                        "type": "integer",
                        "description": "最多返回多少条意向评论，默认 80",
                    },
                },
            },
        },
    },
]
