from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.models.content_comment import ContentComment
from app.services.agent_async_job_service import AgentAsyncJob
from app.services.agent_job_sync_service import AgentJobSyncService, verify_sync_signature


def _test_settings(tmp_path, **kwargs) -> Settings:
    settings = Settings(storage_root=tmp_path / "storage", **kwargs)
    settings.report_output_dir = tmp_path / "reports"
    settings.report_output_dir.mkdir(parents=True, exist_ok=True)
    return settings


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


def test_sync_payload_includes_correlation(tmp_path):
    settings = _test_settings(tmp_path)
    job = AgentAsyncJob(
        job_id="sync-corr",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="completed",
        correlation={"external_system": "aisales", "external_task_id": "task-1"},
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.finished")

    assert payload["correlation"]["external_task_id"] == "task-1"


def test_sync_payload_has_stable_contract(tmp_path):
    settings = _test_settings(tmp_path)
    job = AgentAsyncJob(
        job_id="sync-job",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="深圳团餐",
        status="completed",
        stage="dream",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        result={
            "summary": "done",
            "data_snapshot": {"progress": {"target_leads": 3, "leads_collected": 2}},
            "supervisor_state": {"comments_captured": 9, "completion_outcome": "source_exhausted"},
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.finished")

    assert payload["schema"] == "huoke.agent_job_sync.v1"
    assert payload["event"] == "job.finished"
    assert payload["job"]["job_id"] == "sync-job"
    assert payload["progress"]["target_leads"] == 3
    assert payload["progress"]["leads_collected"] == 2
    assert payload["progress"]["comments_captured"] == 9
    assert isinstance(payload["leads"], list)


def test_sync_payload_includes_lead_evaluation(tmp_path):
    settings = _test_settings(tmp_path)
    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "source": "auto_generated",
        "criteria": {"accept_description": "询价"},
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-eval",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="深圳团餐",
        status="running",
        result={
            "orchestration": {
                "task_brief": {"constraints": {"lead_evaluation": spec}},
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.progress")

    assert payload["lead_evaluation"] == spec


def test_sync_payload_includes_captured_comments(tmp_path, db_session):
    from app.models.content_comment import ContentComment
    from datetime import datetime, timezone

    settings = _test_settings(tmp_path)
    now = datetime.now(timezone.utc)
    db_session.add(
        ContentComment(
            tenant_id="default",
            platform="douyin",
            content_id="vid-1",
            comment_id="cmt-1",
            nickname="测试用户",
            comment_text="想了解 ai获客 方案",
            digg_count=0,
            create_time=1_700_000_000,
            content_url="https://example.test/video/1",
            raw_data={"avatar": "https://example.test/avatar.jpg"},
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.commit()

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-captured",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "job_content_ids": ["vid-1"],
                "evaluation_cache": {
                    "cmt-1": {
                        "is_lead": True,
                        "score": 0.8,
                        "worth_outreach": True,
                        "reason": "有购买意向",
                    }
                }
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 1
    row = payload["captured_comments"][0]
    assert row["nickname"] == "测试用户"
    assert row["avatar_url"] == "https://example.test/avatar.jpg"
    assert "ai获客" in row["comment_content"]
    assert row["is_precise"] is True


def test_captured_comments_scoped_to_job_content_ids(tmp_path, db_session):
    from datetime import datetime, timezone

    settings = _test_settings(tmp_path)
    now = datetime.now(timezone.utc)
    db_session.add(
        ContentComment(
            tenant_id="default",
            platform="douyin",
            content_id="vid-job",
            comment_id="cmt-job",
            nickname="任务用户",
            comment_text="本任务评论",
            digg_count=0,
            create_time=1_700_000_000,
            content_url="https://example.test/video/job",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.add(
        ContentComment(
            tenant_id="default",
            platform="douyin",
            content_id="vid-other",
            comment_id="cmt-other",
            nickname="其他用户",
            comment_text="其他任务评论",
            digg_count=0,
            create_time=1_700_000_001,
            content_url="https://example.test/video/other",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.commit()

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-scope",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "job_content_ids": ["vid-job"],
                "evaluation_cache": {
                    "cmt-job": {"score": 0.8, "worth_outreach": True, "reason": "有意向"},
                    "cmt-other": {"score": 0.9, "worth_outreach": True, "reason": "应被过滤"},
                },
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 1
    assert payload["captured_comments"][0]["comment_id"] == "cmt-job"


def test_captured_comments_exclude_unevaluated_video_comments(tmp_path, db_session):
    from datetime import datetime, timezone

    settings = _test_settings(tmp_path)
    now = datetime.now(timezone.utc)
    for idx in range(3):
        db_session.add(
            ContentComment(
                tenant_id="default",
                platform="douyin",
                content_id="vid-job",
                comment_id=f"cmt-{idx}",
                nickname=f"用户{idx}",
                comment_text=f"评论{idx}",
                digg_count=0,
                create_time=1_700_000_000 + idx,
                content_url="https://example.test/video/job",
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    db_session.commit()

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-evaluated-only",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "job_content_ids": ["vid-job"],
                "job_evaluation_comment_ids": ["cmt-0", "cmt-1"],
                "evaluation_cache": {
                    "cmt-0": {"score": 0.8, "worth_outreach": True, "reason": "有意向"},
                    "cmt-1": {"score": 0.4, "worth_outreach": False, "reason": "无关"},
                    "cmt-2": {"score": 0.9, "worth_outreach": True, "reason": "未纳入任务"},
                },
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 2
    assert {row["comment_id"] for row in payload["captured_comments"]} == {"cmt-0", "cmt-1"}


def test_captured_comments_fallback_to_report_json(tmp_path, db_session):
    settings = _test_settings(tmp_path)
    report_path = settings.report_output_dir / "comments_douyin_default_vid-json.json"
    report_path.write_text(
        json.dumps(
            {
                "platform": "douyin",
                "content_id": "vid-json",
                "video_url": "https://www.douyin.com/video/vid-json",
                "keyword_context": {"keyword": "ai获客"},
                "comments": [
                    {
                        "comment_id": "cmt-json",
                        "comment": "怎么做的",
                        "nickname": "测试用户",
                        "create_time": 1_700_000_000,
                        "avatar": "https://example.test/avatar.jpg",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id="sync-json-fallback",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "evaluation_cache": {
                    "cmt-json": {
                        "score": 0.8,
                        "worth_outreach": True,
                        "reason": "询问怎么做的，表明对操作方法感兴趣",
                    }
                }
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 1
    row = payload["captured_comments"][0]
    assert row["nickname"] == "测试用户"
    assert row["comment_content"] == "怎么做的"
    assert row["evaluation_reason"] == "询问怎么做的，表明对操作方法感兴趣"
    assert row["avatar_url"] == "https://example.test/avatar.jpg"
    assert row["video_title"] == "ai获客"


def test_captured_comments_exclude_other_task_keyword_reports(tmp_path, db_session):
    settings = _test_settings(tmp_path)
    (settings.report_output_dir / "comments_douyin_default_ai-job.json").write_text(
        json.dumps(
            {
                "platform": "douyin",
                "content_id": "vid-ai",
                "keyword_context": {"keyword": "ai获客"},
                "comments": [{"comment_id": "cmt-ai", "comment": "想了解ai获客", "nickname": "AI用户"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (settings.report_output_dir / "comments_douyin_default_tuancan-job.json").write_text(
        json.dumps(
            {
                "platform": "douyin",
                "content_id": "vid-tuancan",
                "keyword_context": {"keyword": "团餐配送"},
                "comments": [{"comment_id": "cmt-tuancan", "comment": "团餐怎么订", "nickname": "团餐用户"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    job = AgentAsyncJob(
        job_id="sync-keyword-scope",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message=json.dumps({"keyword": "ai获客", "task_name": "ai获客"}, ensure_ascii=False),
        status="pending",
        result={
            "supervisor_state": {
                "evaluation_cache": {
                    "cmt-ai": {"score": 0.8, "worth_outreach": True, "reason": "ai意向"},
                    "cmt-tuancan": {"score": 0.9, "worth_outreach": True, "reason": "团餐意向"},
                }
            }
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert {row["comment_id"] for row in payload["captured_comments"]} == {"cmt-ai"}


def test_captured_comments_exclude_other_job_same_video(tmp_path, db_session):
    from datetime import datetime, timezone

    settings = _test_settings(tmp_path)
    now = datetime.now(timezone.utc)
    job_a = "job-alpha"
    job_b = "job-beta"
    for comment_id, job_id, text in (
        ("cmt-a", job_a, "任务A评论"),
        ("cmt-b", job_b, "任务B评论"),
    ):
        db_session.add(
            ContentComment(
                tenant_id="default",
                platform="douyin",
                content_id="vid-shared",
                comment_id=comment_id,
                nickname=f"用户-{comment_id}",
                comment_text=text,
                digg_count=0,
                create_time=1_700_000_000,
                content_url="https://example.test/video/shared",
                raw_data={"_agent_meta": {"source_job_id": job_id}},
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    db_session.commit()

    spec = {
        "schema": "huoke.lead_evaluation.v1",
        "version": 1,
        "thresholds": {"precise": 0.72, "outreach": 0.55},
    }
    job = AgentAsyncJob(
        job_id=job_a,
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="共享视频任务A",
        status="pending",
        result={
            "orchestration": {"task_brief": {"constraints": {"lead_evaluation": spec}}},
            "supervisor_state": {
                "job_content_ids": ["vid-shared"],
                "job_persisted_comment_ids": ["cmt-a"],
                "evaluation_cache": {
                    "cmt-a": {"score": 0.8, "worth_outreach": True, "reason": "A有意向"},
                    "cmt-b": {"score": 0.9, "worth_outreach": True, "reason": "B不应出现"},
                },
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot", db_session=db_session)

    assert len(payload["captured_comments"]) == 1
    assert payload["captured_comments"][0]["comment_id"] == "cmt-a"


def test_sync_payload_includes_suspend_brief(tmp_path):
    settings = _test_settings(tmp_path)
    job = AgentAsyncJob(
        job_id="sync-suspend",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="ai获客",
        status="pending",
        result={
            "summary": "今日配额已用尽",
            "supervisor_state": {
                "suspended": True,
                "wake_reason": "今日配额已用尽，按策略挂起等待下次唤醒",
                "resume_at": "2026-06-18T00:00:00+00:00",
                "next_action": "自动恢复后：同步今日 reply/follow/dm 配额 → 从已入库评论继续独立触达",
                "completion_outcome": "quota_exhausted",
            },
        },
    )

    payload = AgentJobSyncService(settings).build_payload(job, event="job.snapshot")

    assert isinstance(payload.get("suspend_brief"), dict)
    assert "配额" in payload["suspend_brief"]["reason"]
    assert payload["suspend_brief"]["next_action"]
    assert payload["suspend_brief"]["resume_at_display"]


def test_sync_signature_roundtrip(tmp_path):
    settings = _test_settings(tmp_path)
    payload = {"schema": "huoke.agent_job_sync.v1", "job": {"job_id": "j1"}}
    headers = AgentJobSyncService(settings).headers_for(payload)

    assert verify_sync_signature(
        payload,
        settings.huoke_bridge_secret,
        headers["X-Huoke-Sync-Timestamp"],
        headers["X-Huoke-Sync-Signature"],
    )


def test_webhook_posts_sync_contract(tmp_path, monkeypatch):
    from app.services.agent_async_job_service import AgentAsyncJobService

    settings = _test_settings(tmp_path, huoke_bridge_secret="sync-secret")
    svc = AgentAsyncJobService(settings)
    job = AgentAsyncJob(
        job_id="webhook-sync",
        tenant_id="default",
        platform="douyin",
        account_id="default",
        message="test",
        status="completed",
        webhook_url="https://example.test/hook",
    )
    seen: dict = {}

    async def capture_post(self, url, *, json=None, headers=None, **kwargs):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers or {}

        class Resp:
            status_code = 200

        return Resp()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "post", capture_post)
    asyncio.run(svc._post_webhook(job))

    assert seen["url"] == "https://example.test/hook"
    assert seen["json"]["schema"] == "huoke.agent_job_sync.v1"
    assert seen["json"]["event"] == "job.finished"
    assert seen["headers"]["X-Huoke-Sync-Signature"].startswith("sha256=")
