import json
import sqlite3

import pytest

from app.core.config import Settings
from app.services.task_brief_service import TaskBrief
from app.services.task_sandbox_service import TaskSandboxService
from app.services.task_schema_service import DEFAULT_LEAD_TASK_SCHEMA


@pytest.fixture
def settings(tmp_path):
    return Settings(storage_root=tmp_path / "storage")


@pytest.fixture
def brief():
    return TaskBrief(
        title="测试沙盒",
        brief_md="# 测试\n\n## 目标\n抓取线索",
        platform="douyin",
        keyword="团餐",
        goals={"target_leads": 20},
    )


@pytest.mark.asyncio
async def test_provision_creates_isolated_sandbox(settings, brief):
    svc = TaskSandboxService(settings, "default")
    manifest = await svc.provision(job_id="job-sbx-1", brief=brief, schema=DEFAULT_LEAD_TASK_SCHEMA)

    assert manifest["job_id"] == "job-sbx-1"
    assert manifest["tables"]
    root = svc.sandbox_path("job-sbx-1")
    assert (root / "db.sqlite").exists()
    assert (root / "schema.json").exists()
    assert (root / "brief.md").exists()
    assert (root / "code" / "helpers.py").exists()
    assert (root / "files" / "crawl").is_dir()

    conn = svc.connect("job-sbx-1")
    assert conn is not None
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "leads" in tables
    assert "outreach_events" in tables


@pytest.mark.asyncio
async def test_destroy_removes_entire_sandbox(settings, brief):
    svc = TaskSandboxService(settings, "default")
    await svc.provision(job_id="job-sbx-2", brief=brief, schema=DEFAULT_LEAD_TASK_SCHEMA)
    assert svc.sandbox_path("job-sbx-2").exists()
    assert svc.destroy("job-sbx-2") is True
    assert not svc.sandbox_path("job-sbx-2").exists()


def test_default_schema_has_core_tables():
    names = {t["name"] for t in DEFAULT_LEAD_TASK_SCHEMA["tables"]}
    assert {"leads", "outreach_events", "crawl_batches", "task_kv"} <= names
