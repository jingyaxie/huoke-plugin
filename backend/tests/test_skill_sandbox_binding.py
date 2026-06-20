from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
from app.services.agent_browser_session import AgentBrowserSession
from app.services.agent_session_binding import bind_session_sandbox, resolve_active_skill_id


def _profile(skill_ids: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(skill_ids=skill_ids or [])


def test_resolve_active_skill_prefers_explicit_order():
    profile = _profile(["check-login", "douyin-keyword-comments"])
    assert resolve_active_skill_id(profile, ["check-login", "douyin-keyword-comments"]) == "check-login"


def test_resolve_active_skill_falls_back_to_profile():
    profile = _profile(["check-login", "reply-comment"])
    assert resolve_active_skill_id(profile, None) == "check-login"


def test_bind_session_sandbox_sets_fields_and_skip_warmup():
    settings = Settings(storage_root=Path("/tmp"))
    session = AgentBrowserSession(
        session_id="s1",
        tenant_id="default",
        platform="douyin",
        settings=settings,
    )
    bind_session_sandbox(
        session,
        agent_profile_id="task-douyin-skill-flow",
        profile_skill_ids=["douyin-keyword-comments", "check-login"],
        explicit_skill_ids={"douyin-keyword-comments"},
    )
    assert session.agent_profile_id == "task-douyin-skill-flow"
    assert session.active_skill_id == "douyin-keyword-comments"
    assert session.skip_home_warmup is True


def test_bind_session_sandbox_sets_stable_mode():
    settings = Settings(storage_root=Path("/tmp"))
    session = AgentBrowserSession(
        session_id="s6",
        tenant_id="default",
        platform="douyin",
        settings=settings,
    )
    bind_session_sandbox(
        session,
        agent_profile_id="task-douyin-skill-flow",
        profile_skill_ids=["douyin-keyword-comments"],
        explicit_skill_ids=["douyin-keyword-comments"],
    )
    assert session.stable_mode is True


def test_bind_session_sandbox_no_warmup_skip_for_other_profile():
    settings = Settings(storage_root=Path("/tmp"))
    session = AgentBrowserSession(
        session_id="s2",
        tenant_id="default",
        platform="douyin",
        settings=settings,
    )
    bind_session_sandbox(
        session,
        agent_profile_id="pipeline-recovery",
        profile_skill_ids=["check-login"],
        explicit_skill_ids=["check-login"],
    )
    assert session.active_skill_id == "check-login"
    assert session.skip_home_warmup is False
