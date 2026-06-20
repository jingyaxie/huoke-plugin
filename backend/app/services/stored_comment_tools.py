from __future__ import annotations

from typing import Any

STORED_COMMENT_READ_TOOLS: frozenset[str] = frozenset(
    {
        "query_stored_contents",
        "query_stored_comments",
        "get_stored_content_detail",
        "get_stored_comment",
    }
)

STORED_COMMENT_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "create_stored_comment",
        "update_stored_comment",
        "delete_stored_comment",
        "delete_stored_content",
    }
)

STORED_COMMENT_TOOL_NAMES: frozenset[str] = STORED_COMMENT_READ_TOOLS | STORED_COMMENT_WRITE_TOOLS

STORED_COMMENT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_stored_contents",
            "description": (
                "【查-列表】从 MySQL content_comments 表按内容聚合，列出已入库视频/笔记摘要。"
                "用户要求「从数据库查」时优先用本工具或 query_stored_comments，不要用 list_local_comment_files。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "offset": {"type": "integer", "description": "分页偏移，默认 0"},
                    "limit": {"type": "integer", "description": "返回条数，默认 20，最大 50"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_stored_comments",
            "description": (
                "【查-搜索】从 MySQL 查询已入库评论，支持按 content_id、评论关键词筛选。"
                "返回 comment_id、content_url、reply_to_user_id 等回复所需字段。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "content_id": {
                        "type": "string",
                        "description": "可选，限定某条视频/笔记",
                    },
                    "comment_text_contains": {
                        "type": "string",
                        "description": "可选，评论正文模糊匹配",
                    },
                    "offset": {"type": "integer", "description": "分页偏移，默认 0"},
                    "limit": {"type": "integer", "description": "返回条数，默认 20，最大 50"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stored_content_detail",
            "description": (
                "【查-详情】从 MySQL 获取单条内容（视频/笔记）及其已入库评论列表。"
                "需要 content_id；比 query_stored_comments 更适合查看某条内容的全部评论。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "content_id": {
                        "type": "string",
                        "description": "视频/笔记 ID（aweme_id / note_id / photo_id）",
                    },
                    "max_comments": {
                        "type": "integer",
                        "description": "最多返回评论条数，默认 50，最大 100",
                    },
                },
                "required": ["content_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stored_comment",
            "description": (
                "【查-单条】从 MySQL 按 comment_id 获取单条评论详情。"
                "建议同时提供 content_id 以避免跨内容 comment_id 冲突。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "comment_id": {
                        "type": "string",
                        "description": "评论 ID",
                    },
                    "content_id": {
                        "type": "string",
                        "description": "可选，限定所属内容",
                    },
                },
                "required": ["comment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_stored_comment",
            "description": (
                "【增】向 MySQL content_comments 表写入单条评论。"
                "若 (tenant, platform, content_id, comment_id) 已存在则更新为 upsert。"
                "用于手工补录或修正入库数据，勿用于替代 content-comments 抓取。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "content_id": {"type": "string", "description": "视频/笔记 ID"},
                    "comment_id": {"type": "string", "description": "评论 ID"},
                    "comment_text": {"type": "string", "description": "评论正文"},
                    "nickname": {"type": "string", "description": "昵称，默认空"},
                    "content_url": {"type": "string", "description": "内容链接"},
                    "parent_comment_id": {"type": "string", "description": "父评论 ID（回复时）"},
                    "digg_count": {"type": "integer", "description": "点赞数，默认 0"},
                    "create_time": {"type": "integer", "description": "评论发布时间戳（秒）"},
                    "raw_data": {
                        "type": "object",
                        "description": "原始 JSON，可含 user_id、photo_author_id 等",
                    },
                },
                "required": ["content_id", "comment_id", "comment_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stored_comment",
            "description": (
                "【改】更新 MySQL 中已入库的单条评论字段。"
                "仅更新传入的字段，未传字段保持不变。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "content_id": {"type": "string", "description": "视频/笔记 ID"},
                    "comment_id": {"type": "string", "description": "评论 ID"},
                    "comment_text": {"type": "string", "description": "新评论正文"},
                    "nickname": {"type": "string", "description": "新昵称"},
                    "digg_count": {"type": "integer", "description": "新点赞数"},
                    "parent_comment_id": {"type": "string", "description": "父评论 ID"},
                    "content_url": {"type": "string", "description": "内容链接"},
                    "raw_data": {"type": "object", "description": "替换 raw_data JSON"},
                    "create_time": {"type": "integer", "description": "评论发布时间戳"},
                },
                "required": ["content_id", "comment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_stored_comment",
            "description": (
                "【删-单条】从 MySQL 删除单条已入库评论。"
                "需要 content_id 与 comment_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "content_id": {"type": "string", "description": "视频/笔记 ID"},
                    "comment_id": {"type": "string", "description": "评论 ID"},
                },
                "required": ["content_id", "comment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_stored_content",
            "description": (
                "【删-整条内容】从 MySQL 删除某条视频/笔记下的全部已入库评论。"
                "不会删除平台侧真实评论，仅清理本地数据库记录。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "平台：douyin / xiaohongshu / kuaishou；默认当前会话平台",
                    },
                    "content_id": {"type": "string", "description": "视频/笔记 ID"},
                },
                "required": ["content_id"],
            },
        },
    },
]
