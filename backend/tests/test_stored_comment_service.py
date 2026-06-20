from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models.content_comment import ContentComment
from app.services.stored_comment_service import StoredCommentService


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


def _insert_ks_comment(session, **overrides):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = ContentComment(
        tenant_id="default",
        platform="kuaishou",
        content_id="3xphoto123",
        comment_id="cmt_ks_001",
        parent_comment_id=None,
        nickname="快手用户",
        comment_text="想了解一下价格",
        digg_count=2,
        create_time=1710000000,
        content_url="https://www.kuaishou.com/short-video/3xphoto123",
        raw_data={"user_id": "3xuser001", "photo_author_id": "3xauthor001"},
        first_seen_at=now,
        last_seen_at=now,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    return row


def test_query_stored_comments_returns_reply_fields(db_session):
    _insert_ks_comment(db_session)
    service = StoredCommentService(db_session, Settings(), tenant_id="default")
    result = service.query_comments(platform="kuaishou", limit=5)
    assert result["source"] == "database"
    assert result["count"] == 1
    comment = result["comments"][0]
    assert comment["comment_id"] == "cmt_ks_001"
    assert comment["reply_to_user_id"] == "3xuser001"
    assert comment["photo_author_id"] == "3xauthor001"
    assert "kuaishou.com" in (comment["content_url"] or "")


def test_query_stored_comments_filter_by_platform(db_session):
    _insert_ks_comment(db_session)
    service = StoredCommentService(db_session, Settings(), tenant_id="default")
    result = service.query_comments(platform="douyin", limit=5)
    assert result["count"] == 0


def test_get_stored_comment_by_id(db_session):
    _insert_ks_comment(db_session)
    service = StoredCommentService(db_session, Settings(), tenant_id="default")
    result = service.get_comment(
        platform="kuaishou",
        comment_id="cmt_ks_001",
        content_id="3xphoto123",
    )
    assert result["status"] == "ok"
    assert result["comment"]["comment_id"] == "cmt_ks_001"


def test_create_update_delete_stored_comment(db_session):
    service = StoredCommentService(db_session, Settings(), tenant_id="default")
    created = service.create_comment(
        platform="kuaishou",
        content_id="3xnewphoto",
        comment_id="cmt_new_001",
        comment_text="初次留言",
        nickname="测试用户",
        content_url="https://www.kuaishou.com/short-video/3xnewphoto",
        raw_data={"user_id": "3xuser_new"},
    )
    assert created["status"] == "ok"
    assert created["action"] == "created"

    updated = service.update_comment(
        platform="kuaishou",
        content_id="3xnewphoto",
        comment_id="cmt_new_001",
        comment_text="更新后的留言",
        digg_count=5,
    )
    assert updated["status"] == "ok"
    assert updated["comment"]["comment"] == "更新后的留言"
    assert updated["comment"]["digg_count"] == 5

    deleted = service.delete_comment(
        platform="kuaishou",
        content_id="3xnewphoto",
        comment_id="cmt_new_001",
    )
    assert deleted["status"] == "ok"
    assert deleted["deleted_count"] == 1

    missing = service.get_comment(
        platform="kuaishou",
        comment_id="cmt_new_001",
        content_id="3xnewphoto",
    )
    assert missing["status"] == "not_found"


def test_delete_stored_content(db_session):
    _insert_ks_comment(db_session)
    _insert_ks_comment(db_session, comment_id="cmt_ks_002", comment_text="第二条")
    service = StoredCommentService(db_session, Settings(), tenant_id="default")
    result = service.delete_content(platform="kuaishou", content_id="3xphoto123")
    assert result["status"] == "ok"
    assert result["deleted_count"] == 2
    assert service.query_comments(platform="kuaishou", limit=10)["count"] == 0


def test_get_content_detail(db_session):
    _insert_ks_comment(db_session)
    service = StoredCommentService(db_session, Settings(), tenant_id="default")
    detail = service.get_content_detail(platform="kuaishou", content_id="3xphoto123")
    assert detail is not None
    assert detail["content_id"] == "3xphoto123"
    assert len(detail["comments"]) == 1
