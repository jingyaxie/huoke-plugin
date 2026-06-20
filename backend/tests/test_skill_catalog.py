from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.schemas.skill import BUILTIN_HANDLERS
from app.services.skill_store import DEPRECATED_SKILL_IDS, SkillStore, resolve_skill_id


def test_global_skills_has_core_builtin_handlers():
    path = Path(__file__).resolve().parents[1] / "storage" / "skills" / "global.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    handlers = {item.get("builtin_handler") for item in payload.get("skills", [])}
    for required in (
        "follow_user",
        "send_dm",
        "reply_comment",
        "query_stored_comments",
        "pipeline_keyword_comments",
        "crawl_keyword_comments",
    ):
        assert required in handlers


def test_builtin_handlers_registry_matches_code():
    assert "pipeline_keyword_comments" in BUILTIN_HANDLERS
    assert "follow_user" in BUILTIN_HANDLERS
    assert "reply_comment" in BUILTIN_HANDLERS
    assert "query_stored_comments" in BUILTIN_HANDLERS


def test_global_skills_exclude_deprecated():
    path = Path(__file__).resolve().parents[1] / "storage" / "skills" / "global.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = {item.get("id") for item in payload.get("skills", [])}
    assert not ids & DEPRECATED_SKILL_IDS


def test_skill_id_aliases_resolve_to_builtin():
    settings = Settings()
    store = SkillStore(settings)
    skill = store.get("default", "douyin-reply-comment")
    assert skill is not None
    assert skill.id == "reply-comment"
    assert resolve_skill_id("search-videos") == "search-content"
