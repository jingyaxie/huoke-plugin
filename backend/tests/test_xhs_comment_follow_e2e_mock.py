from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models.content_comment import ContentComment
from app.schemas.skill import SkillOut
from app.services.comment_reply_service import CommentReplyService
from app.services.skill_executor import SkillExecutor
from app.services.social_roam.human.xiaohongshu.reply_warm_publish import (
    CAPTURE_METHOD,
    CAPTURE_METHOD_DRY,
    CAPTURE_METHOD_FALLBACK,
    warm_publish_reply_comment,
)
from app.services.social_roam.human.xiaohongshu.warm_outreach_profile import (
    CAPTURE_METHOD as OUTREACH_CAPTURE_METHOD,
    warm_outreach_follow_from_comment,
)
from tests.xhs_mock_page import FakeXhsSessionStore, MockLocator, make_mock_page

NOTE_ID = "663a0e0e000000001e036abc"
COMMENT_ID = "6a0e60ed000000002b02bf0e"
USER_ID = "5f8a1234567890abcdef"
NOTE_URL = (
    f"https://www.xiaohongshu.com/explore/{NOTE_ID}"
    "?xsec_token=mock_token&xsec_source=pc_feed"
)
REPLY_TEXT = "感谢分享，已私信联系～"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def xhs_settings(tmp_path):
    settings = Settings(
        storage_root=tmp_path / "storage",
        report_output_dir=tmp_path / "reports",
        antibot_require_login=False,
    )
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.report_output_dir.mkdir(parents=True, exist_ok=True)
    return settings


@pytest.fixture()
def xhs_store():
    return FakeXhsSessionStore()


def _insert_xhs_comment(session, **overrides):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = ContentComment(
        tenant_id="default",
        platform="xiaohongshu",
        content_id=NOTE_ID,
        comment_id=COMMENT_ID,
        parent_comment_id=None,
        nickname="评论用户",
        comment_text="想了解一下价格",
        digg_count=0,
        create_time=1710000000,
        content_url=NOTE_URL,
        raw_data={"user_id": USER_ID, "note_id": NOTE_ID},
        first_seen_at=now,
        last_seen_at=now,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    return row


def _skill(handler: str) -> SkillOut:
    return SkillOut(
        id="test-skill",
        name="test",
        description="test",
        type="builtin",
        builtin_handler=handler,
        tool_name="skill_test",
    )


@pytest.mark.asyncio
async def test_patch_comment_post_body_fallback():
    from app.services.social_roam.human.xiaohongshu.reply_warm_publish import _patch_comment_post_body

    raw = '{"note_id":"old","target_comment_id":"wrong","content":"hi"}'
    patched = _patch_comment_post_body(
        raw,
        note_id=NOTE_ID,
        comment_id=COMMENT_ID,
        reply_text=REPLY_TEXT,
        parent_comment_id="parent123",
    )
    body = json.loads(patched)
    assert body["note_id"] == NOTE_ID
    assert body["target_comment_id"] == COMMENT_ID
    assert body["content"] == REPLY_TEXT


@pytest.mark.asyncio
async def test_warm_publish_reply_comment_dry_run(xhs_settings):
    page = make_mock_page(url=NOTE_URL)

    with (
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._ensure_note_url_loaded",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._try_open_reply_compose",
            AsyncMock(return_value="target"),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._type_into_reply_input",
            AsyncMock(return_value=True),
        ),
    ):
        result = await warm_publish_reply_comment(
            page,
            xhs_settings,
            tenant_id="default",
            content_url=NOTE_URL,
            comment_id=COMMENT_ID,
            reply_text=REPLY_TEXT,
            note_id=NOTE_ID,
            dry_run=True,
        )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["capture_method"] == CAPTURE_METHOD_DRY
    assert result["reply_mode"] == "target"
    assert result["would_publish"]["target_comment_id"] == COMMENT_ID
    assert "typed" in result["steps"]


@pytest.mark.asyncio
async def test_warm_publish_fallback_dry_run(xhs_settings):
    page = make_mock_page(url=NOTE_URL)

    with (
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._ensure_note_url_loaded",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._try_open_reply_compose",
            AsyncMock(return_value="fallback_patch"),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._type_into_reply_input",
            AsyncMock(return_value=True),
        ),
    ):
        result = await warm_publish_reply_comment(
            page,
            xhs_settings,
            tenant_id="default",
            content_url=NOTE_URL,
            comment_id=COMMENT_ID,
            reply_text=REPLY_TEXT,
            note_id=NOTE_ID,
            dry_run=True,
        )

    assert result["ok"] is True
    assert result["reply_mode"] == "fallback_patch"
    assert "input=fallback_random_reply_button" in result["steps"]


@pytest.mark.asyncio
async def test_warm_publish_reply_comment_publishes_via_api(xhs_settings):
    page = make_mock_page(url=NOTE_URL)

    with (
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._ensure_note_url_loaded",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._try_open_reply_compose",
            AsyncMock(return_value="target"),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._type_into_reply_input",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.reply_warm_publish._click_send_and_wait_post",
            AsyncMock(side_effect=lambda *_a, publish_result, **_k: publish_result.update({"ok": True, "code": 0}) or True),
        ),
    ):
        result = await warm_publish_reply_comment(
            page,
            xhs_settings,
            tenant_id="default",
            content_url=NOTE_URL,
            comment_id=COMMENT_ID,
            reply_text=REPLY_TEXT,
            note_id=NOTE_ID,
            dry_run=False,
        )

    assert result["ok"] is True
    assert result["capture_method"] == CAPTURE_METHOD
    assert result["publish"]["ok"] is True
    assert result["would_publish"]["submit"] == "native_ui_comment_post"


@pytest.mark.asyncio
async def test_warm_outreach_follow_from_comment_dry_run(xhs_settings):
    page = make_mock_page(url=NOTE_URL)
    profile_page = make_mock_page(url=f"https://www.xiaohongshu.com/user/profile/{USER_ID}")

    with (
        patch(
            "app.services.social_roam.human.xiaohongshu.warm_outreach_profile._open_commenter_profile",
            AsyncMock(return_value=(profile_page, f"https://www.xiaohongshu.com/user/profile/{USER_ID}")),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.warm_outreach_profile._warmup_browse_profile",
            AsyncMock(return_value=None),
        ),
    ):
        result = await warm_outreach_follow_from_comment(
            page,
            xhs_settings,
            tenant_id="default",
            account_id="default",
            content_url=NOTE_URL,
            comment_id=COMMENT_ID,
            user_id=USER_ID,
            nickname="评论用户",
            dry_run=True,
        )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["capture_method"] == OUTREACH_CAPTURE_METHOD
    assert result["follow"]["reason"] == "dry_run"
    assert "profile_goto_direct" in result["steps"]


@pytest.mark.asyncio
async def test_warm_outreach_follow_from_comment_clicks_follow(xhs_settings):
    page = make_mock_page(url=NOTE_URL)
    profile_page = make_mock_page(
        url=f"https://www.xiaohongshu.com/user/profile/{USER_ID}",
        locator=MockLocator(inner_text="关注"),
    )

    with (
        patch(
            "app.services.social_roam.human.xiaohongshu.warm_outreach_profile._open_commenter_profile",
            AsyncMock(return_value=(profile_page, f"https://www.xiaohongshu.com/user/profile/{USER_ID}")),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.warm_outreach_profile._warmup_browse_profile",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.social_roam.human.xiaohongshu.warm_outreach_profile._human_follow_on_profile",
            AsyncMock(return_value={"ok": True, "skipped": False, "follow_status_after_text": "已关注"}),
        ),
    ):
        result = await warm_outreach_follow_from_comment(
            page,
            xhs_settings,
            tenant_id="default",
            account_id="default",
            content_url=NOTE_URL,
            comment_id=COMMENT_ID,
            user_id=USER_ID,
            dry_run=False,
            do_follow=True,
        )

    assert result["ok"] is True
    assert result["follow"]["ok"] is True
    assert "follow_clicked" in result["steps"]


@pytest.mark.asyncio
async def test_comment_reply_service_xhs_warm_publish_path(db_session, xhs_settings):
    _insert_xhs_comment(db_session)
    page = make_mock_page(url=NOTE_URL)
    service = CommentReplyService(
        xhs_settings,
        tenant_id="default",
        platform="xiaohongshu",
        session=db_session,
    )

    with patch(
        "app.services.social_roam.human.xiaohongshu.reply_warm_publish.warm_publish_reply_comment",
        AsyncMock(
            return_value={
                "ok": True,
                "dry_run": False,
                "capture_method": CAPTURE_METHOD,
                "comment_id": COMMENT_ID,
                "steps": ["typed"],
            }
        ),
    ) as warm_mock:
        result = await service.reply_comment(
            comment_id=COMMENT_ID,
            reply_text=REPLY_TEXT,
            page=page,
            warm_publish=True,
        )

    assert result["status"] == "completed"
    assert result["platform"] == "xiaohongshu"
    assert result["capture_method"] == CAPTURE_METHOD
    warm_mock.assert_awaited_once()


def test_xhs_resolve_target_from_db(db_session, xhs_settings):
    _insert_xhs_comment(db_session)
    service = CommentReplyService(
        xhs_settings,
        tenant_id="default",
        platform="xiaohongshu",
        session=db_session,
    )
    target = service.resolve_target(comment_id=COMMENT_ID)
    assert not isinstance(target, dict)
    assert target.content_id == NOTE_ID
    assert target.content_url == NOTE_URL


@pytest.mark.asyncio
async def test_skill_executor_xhs_reply_warm_publish(xhs_settings):
    session = MagicMock()
    session.account_id = "default"
    session.is_started = True
    session.page = make_mock_page(url=NOTE_URL)

    executor = SkillExecutor(
        settings=xhs_settings,
        tenant_id="default",
        platform="xiaohongshu",
        session=session,
        pw_executor=MagicMock(),
        db_session=MagicMock(),
    )
    executor._record_interaction_log = MagicMock()

    with patch.object(
        CommentReplyService,
        "reply_comment",
        AsyncMock(
            return_value={
                "status": "completed",
                "platform": "xiaohongshu",
                "comment_id": COMMENT_ID,
                "capture_method": CAPTURE_METHOD,
                "reply_text": REPLY_TEXT,
            }
        ),
    ) as reply_mock:
        result = await executor._execute_reply_comment(
            _skill("reply_comment"),
            {
                "comment_id": COMMENT_ID,
                "reply_text": REPLY_TEXT,
                "warm_publish": True,
                "content_url": NOTE_URL,
            },
        )

    assert result["status"] == "completed"
    assert result["handler"] == "reply_comment"
    reply_mock.assert_awaited_once()
    assert reply_mock.await_args.kwargs.get("warm_publish") is True


@pytest.mark.asyncio
async def test_skill_executor_xhs_warm_outreach_follow(xhs_settings):
    page = make_mock_page(url=NOTE_URL)
    session = MagicMock()
    session.account_id = "default"
    session.is_started = True
    session.page = page

    executor = SkillExecutor(
        settings=xhs_settings,
        tenant_id="default",
        platform="xiaohongshu",
        session=session,
        pw_executor=MagicMock(),
        db_session=MagicMock(),
    )
    executor._record_interaction_log = MagicMock()

    with patch(
        "app.services.social_roam.human.xiaohongshu.warm_outreach_profile.warm_outreach_follow_from_comment",
        AsyncMock(
            return_value={
                "ok": True,
                "capture_method": OUTREACH_CAPTURE_METHOD,
                "user_id": USER_ID,
                "profile_url": f"https://www.xiaohongshu.com/user/profile/{USER_ID}",
                "steps": ["note_ready", "follow_clicked"],
                "follow": {"ok": True},
                "dm": {"ok": False, "skipped": True, "reason": "xhs_pc_no_dm"},
            }
        ),
    ):
        result = await executor._execute_follow(
            {
                "user_id": USER_ID,
                "content_url": NOTE_URL,
                "comment_id": COMMENT_ID,
                "warm_outreach": True,
                "do_follow": True,
            },
            action="follow",
        )

    assert result["status"] == "completed"
    assert result["handler"] == "warm_outreach_from_comment"
    assert result["follow"]["ok"] is True
    assert result["user_id"] == USER_ID


@pytest.mark.asyncio
async def test_skill_executor_xhs_follow_requires_warm_outreach(xhs_settings, xhs_store):
    session = MagicMock()
    session.account_id = "default"
    session.is_started = False

    executor = SkillExecutor(
        settings=xhs_settings,
        tenant_id="default",
        platform="xiaohongshu",
        session=session,
        pw_executor=MagicMock(),
        db_session=MagicMock(),
    )
    executor._record_interaction_log = MagicMock()

    result = await executor._execute_follow(
        {"user_id": USER_ID, "username": "目标"},
        action="follow",
    )

    assert result["status"] == "failed"
    assert "warm_outreach" in result["error"]
