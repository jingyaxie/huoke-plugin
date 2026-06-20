from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.services.task_brief_service import TaskBrief
from app.services.task_schema_service import DEFAULT_HELPER_CODE, DEFAULT_LEAD_TASK_SCHEMA, design_task_schema

SANDBOX_SUBDIRS = ("files", "files/crawl", "files/exports", "code", "logs", "data")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskSandboxService:
    """每任务独立沙盒：目录 + SQLite + schema + 辅助代码。"""

    def __init__(self, settings: Settings, tenant_id: str) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.root = settings.storage_root / "tenants" / tenant_id / "job_sandboxes"

    def sandbox_path(self, job_id: str) -> Path:
        return self.root / job_id

    async def provision(
        self,
        *,
        job_id: str,
        brief: TaskBrief,
        message: str = "",
        provider: str = "deepseek",
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """创建任务沙盒：目录树、schema、db、helpers。"""
        path = self.sandbox_path(job_id)
        if path.exists():
            return self.load_manifest(job_id) or {}

        path.mkdir(parents=True, exist_ok=True)
        for sub in SANDBOX_SUBDIRS:
            (path / sub).mkdir(parents=True, exist_ok=True)

        schema_data = schema or await design_task_schema(
            brief, message, settings=self.settings, provider=provider
        )
        (path / "brief.md").write_text(brief.brief_md or "", encoding="utf-8")
        (path / "schema.json").write_text(
            json.dumps(schema_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (path / "code" / "helpers.py").write_text(DEFAULT_HELPER_CODE, encoding="utf-8")
        (path / "code" / "README.md").write_text(
            "# 任务沙盒代码区\n\n可放置本任务专用辅助脚本；Supervisor 后续可加载执行。\n",
            encoding="utf-8",
        )

        db_path = path / "db.sqlite"
        self._init_database(db_path, schema_data)

        manifest = {
            "job_id": job_id,
            "tenant_id": self.tenant_id,
            "created_at": _utc_now_iso(),
            "root": str(path.resolve()),
            "db_path": str(db_path.resolve()),
            "schema_version": int(schema_data.get("version") or 1),
            "tables": [t.get("name") for t in schema_data.get("tables") or [] if isinstance(t, dict)],
            "description": schema_data.get("description") or "",
            "llm_designed_schema": schema is None,
        }
        (path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest

    def load_manifest(self, job_id: str) -> dict[str, Any] | None:
        manifest_path = self.sandbox_path(job_id) / "manifest.json"
        if not manifest_path.exists():
            return None
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def connect(self, job_id: str) -> sqlite3.Connection | None:
        manifest = self.load_manifest(job_id)
        if not manifest:
            return None
        db_path = manifest.get("db_path") or str(self.sandbox_path(job_id) / "db.sqlite")
        if not Path(db_path).exists():
            return None
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def destroy(self, job_id: str) -> bool:
        """删除整个任务沙盒（一键清理）。"""
        path = self.sandbox_path(job_id)
        if not path.exists():
            return False
        shutil.rmtree(path)
        return True

    def _init_database(self, db_path: Path, schema: dict[str, Any]) -> None:
        conn = sqlite3.connect(db_path)
        try:
            for table in schema.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                name = str(table.get("name") or "").strip()
                columns = table.get("columns")
                if not name or not isinstance(columns, list):
                    continue
                col_defs: list[str] = []
                for col in columns:
                    if not isinstance(col, dict):
                        continue
                    cname = str(col.get("name") or "").strip()
                    ctype = str(col.get("type") or "TEXT").strip().upper()
                    if ctype not in {"INTEGER", "TEXT", "REAL"}:
                        ctype = "TEXT"
                    part = f"{cname} {ctype}"
                    if col.get("primary_key"):
                        part += " PRIMARY KEY"
                    default = col.get("default")
                    if default is not None:
                        part += f" DEFAULT {default}"
                    col_defs.append(part)
                if col_defs:
                    sql = f"CREATE TABLE IF NOT EXISTS {name} ({', '.join(col_defs)})"
                    conn.execute(sql)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def default_schema() -> dict[str, Any]:
        return dict(DEFAULT_LEAD_TASK_SCHEMA)
