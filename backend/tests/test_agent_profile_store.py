from __future__ import annotations

import pytest

from app.services.agent_profile_store import AgentProfileStore
from app.schemas.agent_profile import AgentProfileCreate, AgentProfileUpdate
from app.core.config import Settings


@pytest.fixture()
def store(tmp_path):
    settings = Settings(storage_root=tmp_path / "storage")
    return AgentProfileStore(settings)


def test_default_profile_always_listed(store):
    items = store.list_all("default")
    assert any(p.id == "default" for p in items)
    default = store.resolve("default", None)
    assert default.id == "default"


def test_create_update_delete_profile(store):
    created = store.create(
        "default",
        AgentProfileCreate(
            id="comment-reply-bot",
            name="评论回复专员",
            description="只负责查库并回复",
            system_prompt="你只处理评论回复，禁止抓取新评论。",
            skill_ids=["reply-comment", "query_stored_comments"],
            platforms=["kuaishou"],
        ),
    )
    assert created.id == "comment-reply-bot"

    updated = store.update(
        "default",
        "comment-reply-bot",
        AgentProfileUpdate(system_prompt="优先从数据库查评论再回复。"),
    )
    assert "数据库" in updated.system_prompt

    assert store.delete("default", "comment-reply-bot")
    assert store.get("default", "comment-reply-bot") is None


def test_resolve_disabled_profile_raises(store):
    store.create(
        "default",
        AgentProfileCreate(
            id="disabled-bot",
            name="禁用",
            system_prompt="test",
            enabled=False,
        ),
    )
    with pytest.raises(ValueError, match="已禁用"):
        store.resolve("default", "disabled-bot")
