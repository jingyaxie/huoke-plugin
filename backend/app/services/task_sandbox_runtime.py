from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from app.core.config import Settings
from app.services.task_brief_service import TaskBrief
from app.services.task_sandbox_service import TaskSandboxService

HELPERS_MODULE_PREFIX = "task_sandbox_helpers_"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskSandboxRuntime:
    """任务沙盒运行时：加载 helpers、读写本地 SQLite、同步 Supervisor 状态。"""

    def __init__(self, settings: Settings, tenant_id: str, job_id: str) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.sandbox = TaskSandboxService(settings, tenant_id)
        self.manifest = self.sandbox.load_manifest(job_id)
        self.available = self.manifest is not None
        self._helpers: ModuleType | None = None

    def load_helpers(self) -> ModuleType | None:
        if not self.available:
            return None
        if self._helpers is not None:
            return self._helpers
        helpers_path = self.sandbox.sandbox_path(self.job_id) / "code" / "helpers.py"
        if not helpers_path.exists():
            return None
        module_name = f"{HELPERS_MODULE_PREFIX}{self.job_id.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, helpers_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        self._helpers = module
        return module

    def _conn(self) -> sqlite3.Connection | None:
        return self.sandbox.connect(self.job_id)

    def get_summary(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False}
        conn = self._conn()
        if conn is None:
            return {"available": False}

        summary: dict[str, Any] = {
            "available": True,
            "job_id": self.job_id,
            "db_path": self.manifest.get("db_path") if self.manifest else "",
            "tables": list(self.manifest.get("tables") or []) if self.manifest else [],
            "leads_total": 0,
            "leads_new": 0,
            "outreach_ok": 0,
            "outreach_failed": 0,
            "crawl_batches": 0,
            "last_crawl_at": None,
            "helpers_loaded": self._helpers is not None,
        }
        try:
            summary["leads_total"] = int(
                conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            )
            summary["leads_new"] = int(
                conn.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'").fetchone()[0]
            )
            summary["outreach_ok"] = int(
                conn.execute(
                    "SELECT COUNT(*) FROM outreach_events WHERE status = 'ok'"
                ).fetchone()[0]
            )
            summary["outreach_failed"] = int(
                conn.execute(
                    "SELECT COUNT(*) FROM outreach_events WHERE status = 'failed'"
                ).fetchone()[0]
            )
            summary["crawl_batches"] = int(
                conn.execute("SELECT COUNT(*) FROM crawl_batches").fetchone()[0]
            )
            summary["crawl_comments_total"] = int(
                conn.execute(
                    "SELECT COALESCE(SUM(comments_captured), 0) FROM crawl_batches WHERE status = 'ok'"
                ).fetchone()[0]
            )
            row = conn.execute(
                "SELECT created_at FROM crawl_batches ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                summary["last_crawl_at"] = row[0]
            kv_rows = conn.execute(
                "SELECT key, value FROM task_kv WHERE key IN ('crawl_done', 'day_index', 'last_action')"
            ).fetchall()
            summary["kv"] = {str(r[0]): r[1] for r in kv_rows}
        finally:
            conn.close()
        return summary

    def sync_supervisor_state(self, state: dict[str, Any]) -> None:
        """从沙盒 SQLite 恢复/对齐 Supervisor 状态。"""
        summary = self.get_summary()
        if not summary.get("available"):
            return
        kv = summary.get("kv") if isinstance(summary.get("kv"), dict) else {}
        crawl_done = str(kv.get("crawl_done") or "").strip()
        comments_total = int(summary.get("crawl_comments_total") or 0)
        if crawl_done == "1" and comments_total > 0:
            state["crawl_done"] = True
            state["comments_captured"] = max(int(state.get("comments_captured") or 0), comments_total)
        outreach_ok = int(summary.get("outreach_ok") or 0)
        if outreach_ok > 0:
            state["leads_collected"] = max(int(state.get("leads_collected") or 0), outreach_ok)

    def reset_crawl_progress(self) -> None:
        """任务重新启动时清除沙盒 crawl 完成标记（保留历史批次供排查）。"""
        if not self.available:
            return
        conn = self._conn()
        if conn is None:
            return
        try:
            conn.execute("DELETE FROM task_kv WHERE key = 'crawl_done'")
            conn.commit()
        finally:
            conn.close()

    def reset_restart_progress(self, *, clear_outreach: bool = True) -> None:
        """任务重新启动时清除会影响 Supervisor 决策的沙盒进度。"""
        if not self.available:
            return
        conn = self._conn()
        if conn is None:
            return
        try:
            conn.execute("DELETE FROM task_kv")
            if clear_outreach:
                conn.execute("DELETE FROM outreach_events")
            conn.commit()
        finally:
            conn.close()

    def kv_set(self, key: str, value: str) -> None:
        conn = self._conn()
        if conn is None:
            return
        try:
            conn.execute(
                """
                INSERT INTO task_kv (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, _utc_now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def record_action(
        self,
        *,
        action: str,
        skill_result: dict[str, Any],
        brief: TaskBrief,
        params: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> None:
        if not self.available:
            return
        ok = not skill_result.get("error") and str(skill_result.get("status", "")).lower() != "failed"
        params = params or {}

        if action == "crawl_keyword" and ok:
            captured = self._record_crawl_batch(skill_result, brief, params, dry_run=dry_run)
            if captured > 0:
                self.kv_set("crawl_done", "1")
            else:
                self.kv_set("crawl_done", "0")
            return

        if action in {"reply", "dm", "follow"}:
            self._record_outreach(action, skill_result, ok=ok, dry_run=dry_run)
            self.kv_set("last_action", action)
            return

        if action == "query_comments" and ok:
            self._record_leads_from_comments(skill_result, brief)

    def suggest_outreach_action(
        self,
        stats: dict[str, Any],
        brief: TaskBrief,
    ) -> str | None:
        helpers = self.load_helpers()
        if helpers is None or not hasattr(helpers, "next_outreach_action"):
            return None
        priority = brief.constraints.get("outreach_priority")
        order: list[str] | None = None
        if isinstance(priority, list):
            order = [str(x) for x in priority if x]
        elif isinstance(priority, str) and priority.strip():
            order = [priority.strip()]
        try:
            return helpers.next_outreach_action(stats, order)
        except Exception:
            return None

    def _record_crawl_batch(
        self,
        skill_result: dict[str, Any],
        brief: TaskBrief,
        params: dict[str, Any],
        *,
        dry_run: bool,
    ) -> int:
        captured = int(skill_result.get("total_comments_captured") or 0)
        videos = int(
            skill_result.get("videos_processed")
            or params.get("crawl_video_limit")
            or params.get("video_limit")
            or 0
        )
        results = skill_result.get("results")
        if isinstance(results, list):
            for row in results:
                if isinstance(row, dict):
                    captured += int(row.get("total_comments_captured") or row.get("comment_count") or 0)
                    videos = max(videos, int(row.get("videos_processed") or 0))

        conn = self._conn()
        if conn is None:
            return captured
        try:
            conn.execute(
                """
                INSERT INTO crawl_batches
                (keyword, videos_processed, comments_captured, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    params.get("keyword") or brief.keyword or "",
                    videos,
                    captured,
                    "ok" if not skill_result.get("error") else "failed",
                    _utc_now_iso(),
                ),
            )
            if dry_run and captured > 0:
                self._insert_mock_leads(conn, brief, count=min(captured, 20))
            conn.commit()
        finally:
            conn.close()
        return captured

    def _insert_mock_leads(self, conn: sqlite3.Connection, brief: TaskBrief, *, count: int) -> None:
        helpers = self.load_helpers()
        keywords = self._match_keywords(brief)
        exclude = self._exclude_words(brief)
        for idx in range(count):
            text = f"模拟评论-{brief.keyword or '获客'}-{idx + 1}"
            if helpers and hasattr(helpers, "match_comment"):
                try:
                    if not helpers.match_comment(text, keywords, exclude):
                        continue
                except Exception:
                    pass
            conn.execute(
                """
                INSERT INTO leads
                (comment_id, content_id, nickname, comment_text, keyword, match_score, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"dry-cmt-{self.job_id[:8]}-{idx}",
                    f"dry-vid-{idx}",
                    f"用户{idx}",
                    text,
                    brief.keyword or "",
                    0.8,
                    "new",
                    _utc_now_iso(),
                ),
            )

    def _record_outreach(
        self,
        action: str,
        skill_result: dict[str, Any],
        *,
        ok: bool,
        dry_run: bool,
    ) -> None:
        conn = self._conn()
        if conn is None:
            return
        comment_id = str(skill_result.get("comment_id") or "").strip() or None
        target_user_id = str(skill_result.get("target_user_id") or "").strip() or None
        reply_text = str(skill_result.get("reply_text") or skill_result.get("message") or "").strip() or None
        if dry_run and not comment_id and not target_user_id:
            seq = int(conn.execute("SELECT COUNT(*) FROM outreach_events").fetchone()[0]) + 1
            comment_id = comment_id or f"dry-cmt-{seq}"
            target_user_id = target_user_id or f"dry-user-{seq}"
        lead_id = None
        if comment_id:
            row = conn.execute(
                "SELECT id FROM leads WHERE comment_id = ? ORDER BY id DESC LIMIT 1",
                (comment_id,),
            ).fetchone()
            if row:
                lead_id = int(row[0])
        try:
            conn.execute(
                """
                INSERT INTO outreach_events
                (lead_id, action, status, comment_id, target_user_id, reply_text, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id,
                    action,
                    "ok" if ok else "failed",
                    comment_id,
                    target_user_id,
                    reply_text,
                    str(skill_result.get("error") or "") or None,
                    _utc_now_iso(),
                ),
            )
            if lead_id and ok:
                conn.execute(
                    "UPDATE leads SET status = ? WHERE id = ?",
                    (action, lead_id),
                )
            conn.commit()
        finally:
            conn.close()

    def _record_leads_from_comments(self, skill_result: dict[str, Any], brief: TaskBrief) -> None:
        result = skill_result.get("result")
        comments: list[Any] = []
        if isinstance(result, dict):
            raw = result.get("comments") or result.get("items") or result.get("data")
            if isinstance(raw, list):
                comments = raw
        elif isinstance(result, list):
            comments = result

        if not comments:
            return

        helpers = self.load_helpers()
        keywords = self._match_keywords(brief)
        exclude = self._exclude_words(brief)
        conn = self._conn()
        if conn is None:
            return
        try:
            for item in comments:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("comment_text") or item.get("text") or "").strip()
                if not text:
                    continue
                if helpers and hasattr(helpers, "match_comment"):
                    try:
                        if not helpers.match_comment(text, keywords, exclude):
                            continue
                    except Exception:
                        continue
                comment_id = str(item.get("comment_id") or item.get("id") or "").strip()
                if comment_id:
                    exists = conn.execute(
                        "SELECT 1 FROM leads WHERE comment_id = ? LIMIT 1",
                        (comment_id,),
                    ).fetchone()
                    if exists:
                        continue
                conn.execute(
                    """
                    INSERT INTO leads
                    (comment_id, content_id, content_url, nickname, comment_text, keyword, match_score, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        comment_id or None,
                        str(item.get("content_id") or item.get("aweme_id") or "") or None,
                        str(item.get("content_url") or item.get("video_url") or "") or None,
                        str(item.get("nickname") or item.get("user_name") or "") or None,
                        text,
                        brief.keyword or "",
                        float(item.get("match_score") or 0.5),
                        "new",
                        _utc_now_iso(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _match_keywords(brief: TaskBrief) -> list[str]:
        raw = brief.constraints.get("match_keywords") or brief.goals.get("match_keywords")
        if isinstance(raw, list):
            return [str(x) for x in raw if x]
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        if brief.keyword:
            return [brief.keyword]
        return []

    @staticmethod
    def _exclude_words(brief: TaskBrief) -> list[str]:
        raw = brief.constraints.get("exclude_keywords") or brief.goals.get("exclude_keywords")
        if isinstance(raw, list):
            return [str(x) for x in raw if x]
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        return ["招聘", "广告", "代理"]
