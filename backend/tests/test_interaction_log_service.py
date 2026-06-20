from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.services.interaction_log_service import InteractionLogService


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


def _service(db_session) -> InteractionLogService:
    return InteractionLogService(db_session, Settings(), tenant_id="default")


def test_record_and_is_comment_replied(db_session):
    service = _service(db_session)
    service.record(
        platform="douyin",
        action="reply",
        status="ok",
        comment_id="cmt_001",
        content_id="vid_001",
        reply_text="您好，私信详聊",
    )
    assert service.is_comment_replied(platform="douyin", comment_id="cmt_001") is True
    assert service.is_comment_replied(platform="douyin", comment_id="cmt_002") is False


def test_failed_reply_does_not_block_retry(db_session):
    service = _service(db_session)
    service.record(
        platform="douyin",
        action="reply",
        status="failed",
        comment_id="cmt_retry",
        error_message="network error",
    )
    assert service.is_comment_replied(platform="douyin", comment_id="cmt_retry") is False
    service.record(
        platform="douyin",
        action="reply",
        status="ok",
        comment_id="cmt_retry",
        reply_text="第二次成功",
    )
    assert service.is_comment_replied(platform="douyin", comment_id="cmt_retry") is True


def test_query_stats_quota(db_session):
    service = _service(db_session)
    for idx in range(3):
        service.record(
            platform="douyin",
            action="reply",
            status="ok",
            comment_id=f"cmt_{idx}",
        )
    stats = service.query_stats(platform="douyin", reply_limit=5, follow_limit=2)
    assert stats["reply"]["count"] == 3
    assert stats["reply"]["remaining"] == 2
    assert stats["reply"]["quota_ok"] is True
    assert stats["follow"]["count"] == 0
    assert stats["follow"]["remaining"] == 2


def test_is_user_followed_by_user_or_sec_uid(db_session):
    service = _service(db_session)
    service.record(
        platform="douyin",
        action="follow",
        status="ok",
        target_user_id="uid_123",
        target_sec_uid="sec_abc",
    )
    assert service.is_user_followed(platform="douyin", target_user_id="uid_123") is True
    assert service.is_user_followed(platform="douyin", target_sec_uid="sec_abc") is True
    assert service.is_user_followed(platform="douyin", target_user_id="uid_other") is False


def test_query_stats_with_comment_and_user_check(db_session):
    service = _service(db_session)
    service.record(
        platform="douyin",
        action="reply",
        status="ok",
        comment_id="cmt_checked",
    )
    result = service.query_stats(
        platform="douyin",
        comment_id="cmt_checked",
        target_user_id="uid_new",
    )
    assert result["is_comment_replied"] is True
    assert result["is_user_followed"] is False


def test_query_logs(db_session):
    service = _service(db_session)
    service.record(platform="douyin", action="reply", status="ok", comment_id="c1")
    service.record(platform="douyin", action="follow", status="ok", target_user_id="u1")
    logs = service.query_logs(platform="douyin", action="reply")
    assert logs["total"] == 1
    assert logs["items"][0]["action"] == "reply"


def test_query_task_ledger_scoped_by_job_id(db_session):
    service = _service(db_session)
    service.record(
        platform="douyin",
        action="reply",
        status="ok",
        comment_id="cmt_job_a",
        task_id="job-a",
        reply_text="你好",
    )
    service.record(
        platform="douyin",
        action="follow",
        status="ok",
        target_user_id="uid_1",
        task_id="job-a",
    )
    service.record(
        platform="douyin",
        action="reply",
        status="ok",
        comment_id="cmt_job_b",
        task_id="job-b",
    )

    ledger_a = service.query_task_ledger(job_id="job-a", platform="douyin")
    assert ledger_a["stats"]["reply"]["ok"] == 1
    assert ledger_a["stats"]["follow"]["ok"] == 1
    assert ledger_a["total_outreach_ok"] == 2
    assert len(ledger_a["comment_status"]) == 1
    assert ledger_a["comment_status"][0]["comment_id"] == "cmt_job_a"

    ledger_b = service.query_task_ledger(job_id="job-b", platform="douyin")
    assert ledger_b["stats"]["reply"]["ok"] == 1
    assert ledger_b["total_outreach_ok"] == 1
