from __future__ import annotations

from app.services.stored_comment_tools import (
    STORED_COMMENT_READ_TOOLS,
    STORED_COMMENT_TOOL_DEFINITIONS,
    STORED_COMMENT_TOOL_NAMES,
    STORED_COMMENT_WRITE_TOOLS,
)


def test_stored_comment_tool_definitions_cover_crud():
    names = {t["function"]["name"] for t in STORED_COMMENT_TOOL_DEFINITIONS}
    assert names == STORED_COMMENT_TOOL_NAMES
    assert STORED_COMMENT_READ_TOOLS == {
        "query_stored_contents",
        "query_stored_comments",
        "get_stored_content_detail",
        "get_stored_comment",
    }
    assert STORED_COMMENT_WRITE_TOOLS == {
        "create_stored_comment",
        "update_stored_comment",
        "delete_stored_comment",
        "delete_stored_content",
    }
    assert len(STORED_COMMENT_TOOL_DEFINITIONS) == 8
