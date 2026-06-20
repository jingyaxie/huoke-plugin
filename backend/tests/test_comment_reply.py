from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models.content_comment import ContentComment
from app.platforms.kuaishou.utils import (
    _walk_photo_author_id,
    extract_comment_user_id,
    extract_user_id_from_profile_href,
    find_comment_author_id,
    normalize_ks_comment,
    parse_video_detail,
    resolve_photo_author_id,
)
from app.repositories.content_comment_repository import ContentCommentRepository
from app.schemas.skill import BUILTIN_HANDLERS
from app.services.comment_reply_service import CommentReplyService


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


def _insert_comment(session, **overrides):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = ContentComment(
        tenant_id="default",
        platform="douyin",
        content_id="7648234202216192997",
        comment_id="7650081143698572051",
        parent_comment_id=None,
        nickname="测试用户",
        comment_text="太快了对面伸手戳到眼睛怎么办",
        digg_count=0,
        create_time=1710000000,
        content_url="https://www.douyin.com/video/7648234202216192997",
        raw_data={"aweme_id": "7648234202216192997"},
        first_seen_at=now,
        last_seen_at=now,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    return row


def test_builtin_handlers_include_reply_comment():
    assert "reply_comment" in BUILTIN_HANDLERS


def test_global_skills_include_reply_comment():
    path = Path(__file__).resolve().parents[1] / "storage" / "skills" / "global.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in payload.get("skills", [])}
    assert by_id["reply-comment"]["type"] == "builtin"
    assert by_id["reply-comment"]["builtin_handler"] == "reply_comment"
    assert "douyin-reply-comment" not in by_id


def test_find_comment_record_by_comment_id(db_session):
    _insert_comment(db_session)
    repo = ContentCommentRepository(db_session, "default")
    row = repo.find_comment_record(platform="douyin", comment_id="7650081143698572051")
    assert row is not None
    assert row.content_id == "7648234202216192997"
    assert "7648234202216192997" in (row.content_url or "")


def test_resolve_target_from_db(db_session):
    _insert_comment(db_session)
    service = CommentReplyService(
        Settings(),
        tenant_id="default",
        platform="douyin",
        session=db_session,
    )
    target = service.resolve_target(comment_id="7650081143698572051")
    assert not isinstance(target, dict)
    assert target.content_id == "7648234202216192997"
    assert target.content_url.endswith("7648234202216192997")


def test_resolve_target_with_url_when_db_missing(db_session):
    service = CommentReplyService(
        Settings(),
        tenant_id="default",
        platform="douyin",
        session=db_session,
    )
    target = service.resolve_target(
        comment_id="999",
        video_url="https://www.douyin.com/video/7648234202216192997",
    )
    assert not isinstance(target, dict)
    assert target.content_id == "7648234202216192997"


def test_resolve_target_fails_without_db_or_url(db_session):
    service = CommentReplyService(
        Settings(),
        tenant_id="default",
        platform="douyin",
        session=db_session,
    )
    result = service.resolve_target(comment_id="999")
    assert isinstance(result, dict)
    assert result.get("status") == "failed"


def test_walk_photo_author_id_from_graphql_payload():
    payload = {
        "data": {
            "visionVideoDetail": {
                "photo": {
                    "id": "3xabc123",
                    "author": {"id": "123456789"},
                }
            }
        }
    }
    assert _walk_photo_author_id(payload, "3xabc123") == "123456789"


def test_parse_video_detail_extracts_author_and_exp_tag():
    payload = {
        "data": {
            "visionVideoDetail": {
                "author": {"id": "3xauthor", "name": "作者"},
                "photo": {"id": "3xphoto", "expTag": "1_a/123_xpc"},
            }
        }
    }
    parsed = parse_video_detail(payload)
    assert parsed["photo_author_id"] == "3xauthor"
    assert parsed["exp_tag"] == "1_a/123_xpc"
    assert parsed["photo_id"] == "3xphoto"


def test_parse_video_detail_reads_author_nested_under_photo():
    payload = {
        "data": {
            "visionVideoDetail": {
                "photo": {
                    "id": "3xabc123",
                    "expTag": "tag",
                    "author": {"id": "3xnested"},
                }
            }
        }
    }
    parsed = parse_video_detail(payload)
    assert parsed["photo_author_id"] == "3xnested"
    assert resolve_photo_author_id(payload, "3xabc123") == "3xnested"


def test_extract_user_id_from_profile_href():
    assert extract_user_id_from_profile_href("/profile/3xabc123") == "3xabc123"
    assert extract_user_id_from_profile_href("https://www.kuaishou.com/profile/3xuser?tab=video") == "3xuser"
    assert extract_user_id_from_profile_href(None) is None


def test_resolve_kuaishou_target_reads_photo_author_from_canonical(db_session, tmp_path):
    content_id = "3xphoto999"
    canonical = tmp_path / f"comments_kuaishou_default_{content_id}.json"
    canonical.write_text(
        json.dumps({"photo_author_id": "3xauthor999", "comments": []}),
        encoding="utf-8",
    )
    settings = Settings()
    settings.report_output_dir = tmp_path
    service = CommentReplyService(
        settings,
        tenant_id="default",
        platform="kuaishou",
        session=db_session,
    )
    target = service.resolve_target(
        comment_id="cmt1",
        video_url=f"https://www.kuaishou.com/short-video/{content_id}",
    )
    assert not isinstance(target, dict)
    assert target.photo_author_id == "3xauthor999"


def test_extract_comment_user_id_from_nested_author():
    row = normalize_ks_comment(
        {
            "commentId": "cmt100",
            "content": "你好",
            "author": {"id": "3xcommenter", "name": "用户A"},
        }
    )
    assert row["user_id"] == "3xcommenter"
    assert extract_comment_user_id(row) == "3xcommenter"
    assert extract_comment_user_id({"user": {"uid": "3xuid"}}) == "3xuid"


def test_resolve_kuaishou_target_reads_reply_to_user_from_canonical(db_session, tmp_path):
    content_id = "3xphoto888"
    canonical = tmp_path / f"comments_kuaishou_default_{content_id}.json"
    canonical.write_text(
        json.dumps(
            {
                "comments": [
                    {"comment_id": "cmt888", "user_id": "3xreplyuser", "comment": "测试"},
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings()
    settings.report_output_dir = tmp_path
    service = CommentReplyService(
        settings,
        tenant_id="default",
        platform="kuaishou",
        session=db_session,
    )
    target = service.resolve_target(
        comment_id="cmt888",
        video_url=f"https://www.kuaishou.com/short-video/{content_id}",
    )
    assert not isinstance(target, dict)
    assert target.reply_to_user_id == "3xreplyuser"


def test_find_comment_author_id_from_normalized_rows():
    rows = [
        {"comment_id": "100", "user_id": "3xuser1"},
        {"comment_id": "200", "user_id": "3xuser2"},
    ]
    assert find_comment_author_id(rows, "200") == "3xuser2"
    assert find_comment_author_id(rows, "999") is None
