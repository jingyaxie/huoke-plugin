from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.agent_async_job_service import AgentAsyncJob
from app.services.lead_evaluation_service import accept_evaluation_result, is_precise_lead
from app.services.task_execution_plan import build_suspend_brief
from app.services.task_round_service import effective_live_leads_qualified
from app.services.task_sandbox_service import TaskSandboxService

SYNC_SCHEMA_VERSION = "huoke.agent_job_sync.v1"
LEAD_EVALUATION_SCHEMA = "huoke.lead_evaluation.v1"


def lead_evaluation_from_job_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    orch = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {}
    brief = orch.get("task_brief") if isinstance(orch.get("task_brief"), dict) else {}
    constraints = brief.get("constraints") if isinstance(brief.get("constraints"), dict) else {}
    spec = constraints.get("lead_evaluation")
    if isinstance(spec, dict) and spec.get("schema") == LEAD_EVALUATION_SCHEMA:
        return spec
    return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sign_sync_payload(payload: dict[str, Any], secret: str, *, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    body = _json_dumps(payload)
    digest = hmac.new(str(secret or "").encode("utf-8"), f"{ts}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "X-Huoke-Sync-Schema": SYNC_SCHEMA_VERSION,
        "X-Huoke-Sync-Timestamp": ts,
        "X-Huoke-Sync-Signature": f"sha256={digest}",
    }


def verify_sync_signature(payload: dict[str, Any], secret: str, timestamp: str, signature: str) -> bool:
    expected = sign_sync_payload(payload, secret, timestamp=timestamp)["X-Huoke-Sync-Signature"]
    return hmac.compare_digest(expected, signature)


def _nickname_from_dict(row: dict[str, Any]) -> str:
    for key in ("nickname", "username", "user_name", "nick_name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    user = row.get("user")
    if isinstance(user, dict):
        for key in ("nickname", "unique_id", "uid"):
            value = str(user.get(key) or "").strip()
            if value:
                return value
    return ""


def _comment_text_from_dict(row: dict[str, Any]) -> str:
    return str(row.get("comment") or row.get("text") or row.get("comment_text") or "").strip()


def _avatar_from_dict(row: dict[str, Any]) -> str:
    for key in ("avatar", "avatar_url", "author_avatar", "author_avatar_url"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    user = row.get("user")
    if isinstance(user, dict):
        for key in ("avatar", "avatar_url"):
            value = str(user.get(key) or "").strip()
            if value:
                return value
        avatar = user.get("avatar_larger") or user.get("avatar_medium") or user.get("avatar_thumb")
        if isinstance(avatar, dict):
            url_list = avatar.get("url_list") or []
            if url_list:
                return str(url_list[0] or "").strip()
    return ""


class AgentJobSyncService:
    """Build the stable external synchronization contract for async jobs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_payload(
        self,
        job: AgentAsyncJob,
        *,
        event: str,
        db_session: Session | None = None,
    ) -> dict[str, Any]:
        result = job.result if isinstance(job.result, dict) else {}
        supervisor_state = result.get("supervisor_state") if isinstance(result.get("supervisor_state"), dict) else {}
        data_snapshot = result.get("data_snapshot") if isinstance(result.get("data_snapshot"), dict) else {}
        progress = data_snapshot.get("progress") if isinstance(data_snapshot.get("progress"), dict) else {}
        task_ledger = result.get("task_ledger") if isinstance(result.get("task_ledger"), dict) else {}
        sandbox = self._sandbox_payload(job)
        leads = sandbox.get("leads") or []
        outreach_events = sandbox.get("outreach_events") or []
        crawl_batches = sandbox.get("crawl_batches") or []
        captured_comments = self._captured_comments_payload(
            job,
            supervisor_state,
            outreach_events,
            db_session=db_session,
        )

        correlation = job.correlation if isinstance(job.correlation, dict) else {}
        payload: dict[str, Any] = {
            "schema": SYNC_SCHEMA_VERSION,
            "event": event,
            "emitted_at": _utc_now_iso(),
            "job": {
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "platform": job.platform,
                "account_id": job.account_id,
                "status": job.status,
                "stage": job.stage,
                "retry_count": int(job.retry_count or 0),
                "run_id": job.run_id,
                "session_id": job.session_id,
                "message": job.message,
                "error": job.error,
                "dead_letter_reason": job.dead_letter_reason,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            },
            "progress": {
                "target_leads": int(progress.get("target_leads") or supervisor_state.get("round_target_leads") or 0),
                "leads_collected": int(progress.get("leads_collected") or supervisor_state.get("leads_collected") or 0),
                "total_leads_collected": int(supervisor_state.get("total_leads_collected") or progress.get("leads_collected") or 0),
                "comments_captured": int(supervisor_state.get("comments_captured") or sandbox.get("summary", {}).get("crawl_comments_total") or 0),
                "comments_evaluated": int(supervisor_state.get("comments_evaluated") or 0),
                "leads_qualified": effective_live_leads_qualified(supervisor_state, job_result=result),
                "completion_outcome": result.get("completion_outcome") or supervisor_state.get("completion_outcome"),
                "resume_at": supervisor_state.get("resume_at"),
                "wake_reason": supervisor_state.get("wake_reason"),
                "next_action": supervisor_state.get("next_action"),
            },
            "stats": {
                "leads_total": len(leads),
                "outreach_total": len(outreach_events),
                "crawl_batches_total": len(crawl_batches),
                "outreach_ok": int(task_ledger.get("total_outreach_ok") or sandbox.get("summary", {}).get("outreach_ok") or 0),
                "outreach_failed": int(sandbox.get("summary", {}).get("outreach_failed") or 0),
            },
            "leads": leads,
            "outreach_events": outreach_events,
            "crawl_batches": crawl_batches,
            "captured_comments": captured_comments,
            "summary": {
                "text": result.get("summary") or "",
                "orchestration": result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {},
                "progress_events": (result.get("progress_events") or [])[-20:] if isinstance(result.get("progress_events"), list) else [],
                "task_ledger": task_ledger,
            },
        }
        if correlation:
            payload["correlation"] = correlation
        lead_evaluation = lead_evaluation_from_job_result(result)
        if lead_evaluation:
            payload["lead_evaluation"] = lead_evaluation
        orchestration = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {}
        task_brief = orchestration.get("task_brief") if isinstance(orchestration.get("task_brief"), dict) else {}
        suspend_brief = build_suspend_brief(supervisor_state, result, task_brief)
        if suspend_brief:
            payload["suspend_brief"] = suspend_brief
        return payload

    def headers_for(self, payload: dict[str, Any]) -> dict[str, str]:
        return sign_sync_payload(payload, self.settings.huoke_bridge_secret)

    def _captured_comments_payload(
        self,
        job: AgentAsyncJob,
        supervisor_state: dict[str, Any],
        outreach_events: list[dict[str, Any]],
        *,
        db_session: Session | None,
    ) -> list[dict[str, Any]]:
        if db_session is None:
            return []

        from app.repositories.content_comment_repository import ContentCommentRepository

        evaluation_cache = supervisor_state.get("evaluation_cache")
        if not isinstance(evaluation_cache, dict):
            evaluation_cache = {}

        platform = str(job.platform or "douyin")
        repo = ContentCommentRepository(db_session, job.tenant_id)
        eval_spec = lead_evaluation_from_job_result(job.result if isinstance(job.result, dict) else {}) or {}
        outreach_by_comment = self._outreach_by_comment(outreach_events)
        scoped_comment_ids = self._job_scoped_comment_ids(
            job,
            supervisor_state,
            outreach_events,
            db_session=db_session,
        )
        if scoped_comment_ids is None or not scoped_comment_ids:
            return []

        records = repo.list_by_comment_ids(
            platform=platform,
            comment_ids=sorted(scoped_comment_ids),
            limit=500,
        )
        record_map = {str(row.comment_id): row for row in records}
        content_ids = self._job_content_ids(job, supervisor_state)
        task_keyword = self._task_keyword(job)
        snapshot_map = self._load_comment_snapshots_from_reports(
            tenant_id=job.tenant_id,
            platform=platform,
            comment_ids=scoped_comment_ids,
            content_ids=content_ids,
            job_id=str(job.job_id or "").strip(),
            task_keyword=task_keyword,
        )
        persisted_ids = {
            str(x).strip()
            for x in (supervisor_state.get("job_persisted_comment_ids") or [])
            if str(x).strip()
        }
        rows: list[dict[str, Any]] = []
        for comment_id in sorted(scoped_comment_ids):
            evaluation = evaluation_cache.get(comment_id)
            if not isinstance(evaluation, dict):
                evaluation = {}
            rows.append(
                self._serialize_captured_comment_row(
                    str(comment_id),
                    evaluation,
                    record=record_map.get(str(comment_id)),
                    snapshot=snapshot_map.get(str(comment_id)),
                    outreach=outreach_by_comment.get(str(comment_id), {}),
                    eval_spec=eval_spec,
                    job_persisted=comment_id in persisted_ids,
                )
            )

        rows.sort(key=lambda item: float(item.get("evaluation_score") or 0), reverse=True)
        return rows

    @staticmethod
    def _outreach_by_comment(outreach_events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        outreach_by_comment: dict[str, dict[str, Any]] = {}
        for event in outreach_events:
            if not isinstance(event, dict):
                continue
            comment_id = str(event.get("comment_id") or "").strip()
            if not comment_id:
                continue
            bucket = outreach_by_comment.setdefault(comment_id, {})
            action = str(event.get("action") or "").strip().lower()
            if action == "reply" and event.get("reply_text"):
                bucket["reply_content"] = str(event.get("reply_text") or "")
            if action == "dm" and event.get("reply_text"):
                bucket["dm_content"] = str(event.get("reply_text") or "")
            if str(event.get("status") or "").lower() == "ok":
                bucket["executed_at"] = event.get("created_at") or bucket.get("executed_at")
        return outreach_by_comment

    @staticmethod
    def _comment_avatar_url(record: Any | None, snapshot: dict[str, Any] | None = None) -> str:
        if record is not None:
            raw = record.raw_data if isinstance(record.raw_data, dict) else {}
            avatar = _avatar_from_dict(raw)
            if avatar:
                return avatar
        if isinstance(snapshot, dict):
            avatar = str(snapshot.get("avatar") or "").strip()
            if avatar:
                return avatar
            raw = snapshot.get("raw_data")
            if isinstance(raw, dict):
                return _avatar_from_dict(raw)
        return ""

    @staticmethod
    def _serialize_captured_comment_row(
        comment_id: str,
        evaluation: dict[str, Any],
        *,
        record: Any | None,
        snapshot: dict[str, Any] | None = None,
        outreach: dict[str, Any],
        eval_spec: dict[str, Any],
        job_persisted: bool = False,
    ) -> dict[str, Any]:
        nickname = str(record.nickname or "").strip() if record is not None else ""
        comment_text = str(record.comment_text or "").strip() if record is not None else ""
        create_time = record.create_time if record is not None else None
        content_url = str(record.content_url or "").strip() if record is not None else ""
        content_id = str(record.content_id or "").strip() if record is not None else ""
        video_title = ""

        if isinstance(snapshot, dict):
            if not nickname:
                nickname = str(snapshot.get("nickname") or "").strip()
            if not comment_text:
                comment_text = str(snapshot.get("comment_text") or "").strip()
            if create_time is None:
                create_time = snapshot.get("create_time")
            if not content_url:
                content_url = str(snapshot.get("video_url") or "").strip()
            if not content_id:
                content_id = str(snapshot.get("content_id") or "").strip()
            video_title = str(snapshot.get("video_title") or "").strip()

        comment_at = ""
        if create_time is not None:
            try:
                comment_at = datetime.fromtimestamp(int(create_time), tz=timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                comment_at = ""
        elif record is not None and record.last_seen_at:
            comment_at = record.last_seen_at.isoformat()

        avatar_url = AgentJobSyncService._comment_avatar_url(record, snapshot)
        precise_from_ctx = False
        if isinstance(snapshot, dict):
            ctx = snapshot.get("keyword_context")
            if isinstance(ctx, dict) and str(ctx.get("status") or "").strip().lower() == "precise":
                precise_from_ctx = True
        if record is not None and isinstance(record.raw_data, dict):
            ctx = record.raw_data.get("keyword_context")
            if isinstance(ctx, dict) and str(ctx.get("status") or "").strip().lower() == "precise":
                precise_from_ctx = True
        if eval_spec:
            is_precise = is_precise_lead(evaluation, eval_spec) or precise_from_ctx or job_persisted
        elif evaluation:
            is_precise = bool(evaluation.get("worth_outreach")) or precise_from_ctx or job_persisted
        else:
            is_precise = precise_from_ctx or job_persisted
        return {
            "id": str(comment_id),
            "comment_id": str(comment_id),
            "nickname": nickname or "—",
            "avatar": avatar_url,
            "avatar_url": avatar_url,
            "comment_content": comment_text,
            "comment_at": comment_at,
            "video_title": video_title,
            "video_url": content_url,
            "content_id": content_id,
            "is_precise": is_precise,
            "evaluation_score": float(evaluation.get("score") or 0),
            "evaluation_reason": str(evaluation.get("reason") or ""),
            "reply_content": outreach.get("reply_content") or "",
            "dm_content": outreach.get("dm_content") or "",
            "executed_at": outreach.get("executed_at") or "",
        }

    def _load_comment_snapshots_from_reports(
        self,
        *,
        tenant_id: str,
        platform: str,
        comment_ids: set[str],
        content_ids: set[str],
        job_id: str = "",
        task_keyword: str = "",
    ) -> dict[str, dict[str, Any]]:
        if not comment_ids:
            return {}

        root = self.settings.report_output_dir
        if not root.exists():
            return {}

        pending = {str(comment_id).strip() for comment_id in comment_ids if str(comment_id).strip()}
        index: dict[str, dict[str, Any]] = {}

        def ingest_payload(data: dict[str, Any]) -> None:
            if not pending:
                return
            if not self._report_payload_belongs_to_job(
                data,
                job_id=job_id,
                content_ids=content_ids,
                task_keyword=task_keyword,
            ):
                return
            video_url = str(data.get("video_url") or data.get("note_url") or "").strip()
            file_content_id = str(
                data.get("content_id") or data.get("aweme_id") or data.get("note_id") or ""
            ).strip()
            keyword_ctx = data.get("keyword_context") if isinstance(data.get("keyword_context"), dict) else {}
            keyword = str(keyword_ctx.get("keyword") or "").strip()
            video_title = str(data.get("title") or data.get("desc") or keyword or "").strip()
            if not video_title and file_content_id:
                video_title = f"视频 {file_content_id[-8:]}"
            for row in data.get("comments") or []:
                if not isinstance(row, dict):
                    continue
                if not self._comment_row_belongs_to_job(row, job_id=job_id, file_belongs=True):
                    continue
                cid = str(row.get("comment_id") or "").strip()
                if cid not in pending:
                    continue
                index[cid] = {
                    "nickname": _nickname_from_dict(row),
                    "comment_text": _comment_text_from_dict(row),
                    "create_time": row.get("create_time"),
                    "avatar": _avatar_from_dict(row),
                    "content_id": file_content_id,
                    "video_url": video_url,
                    "video_title": video_title,
                    "raw_data": row,
                }
                pending.discard(cid)

        for content_id in content_ids:
            if not pending:
                break
            canonical = root / f"comments_{platform}_{tenant_id}_{content_id}.json"
            if not canonical.is_file():
                continue
            try:
                ingest_payload(json.loads(canonical.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue

        if pending:
            pattern = f"comments_{platform}_{tenant_id}_*.json"
            files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            for path in files:
                if not pending:
                    break
                try:
                    ingest_payload(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue

        return index

    @staticmethod
    def _task_keyword(job: AgentAsyncJob) -> str:
        message = job.message
        if isinstance(message, str) and message.strip().startswith("{"):
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                keyword = str(payload.get("keyword") or "").strip()
                if keyword:
                    return keyword

        result = job.result if isinstance(job.result, dict) else {}
        orchestration = result.get("orchestration") if isinstance(result.get("orchestration"), dict) else {}
        brief = orchestration.get("task_brief") if isinstance(orchestration.get("task_brief"), dict) else {}
        keyword = str(brief.get("keyword") or "").strip()
        if keyword:
            return keyword

        constraints = brief.get("constraints") if isinstance(brief.get("constraints"), dict) else {}
        lead_evaluation = constraints.get("lead_evaluation") if isinstance(constraints.get("lead_evaluation"), dict) else {}
        business_context = (
            lead_evaluation.get("business_context")
            if isinstance(lead_evaluation.get("business_context"), dict)
            else {}
        )
        keyword = str(business_context.get("keyword") or "").strip()
        if keyword:
            return keyword

        if isinstance(message, str):
            plain = message.strip()
            if plain and not plain.startswith("{") and len(plain) <= 64 and "\n" not in plain:
                return plain
        return ""

    @staticmethod
    def _content_comment_belongs_to_job(record: Any, job_id: str) -> bool:
        if not job_id:
            return True
        raw = record.raw_data if isinstance(getattr(record, "raw_data", None), dict) else {}
        meta = raw.get("_agent_meta") if isinstance(raw.get("_agent_meta"), dict) else {}
        stored = str(meta.get("source_job_id") or "").strip()
        return stored == job_id

    @staticmethod
    def _comment_row_belongs_to_job(row: dict[str, Any], *, job_id: str, file_belongs: bool) -> bool:
        if not file_belongs:
            return False
        if not job_id:
            return True
        meta = row.get("_agent_meta") if isinstance(row.get("_agent_meta"), dict) else {}
        stored_job_id = str(meta.get("source_job_id") or "").strip()
        if stored_job_id:
            return stored_job_id == job_id
        return file_belongs

    @staticmethod
    def _report_payload_belongs_to_job(
        data: dict[str, Any],
        *,
        job_id: str,
        content_ids: set[str],
        task_keyword: str,
    ) -> bool:
        file_content_id = str(
            data.get("content_id") or data.get("aweme_id") or data.get("note_id") or ""
        ).strip()
        if content_ids and file_content_id and file_content_id in content_ids:
            return True

        keyword_ctx = data.get("keyword_context") if isinstance(data.get("keyword_context"), dict) else {}
        file_keyword = str(keyword_ctx.get("keyword") or "").strip()
        if task_keyword and file_keyword == task_keyword:
            return True

        if not job_id:
            return False
        for row in data.get("comments") or []:
            if not isinstance(row, dict):
                continue
            meta = row.get("_agent_meta") if isinstance(row.get("_agent_meta"), dict) else {}
            if str(meta.get("source_job_id") or "").strip() == job_id:
                return True
        return False

    def _comment_ids_from_reports_for_job(
        self,
        *,
        tenant_id: str,
        platform: str,
        job_id: str,
        content_ids: set[str],
        task_keyword: str,
        candidate_ids: set[str] | None = None,
    ) -> set[str]:
        root = self.settings.report_output_dir
        if not root.exists():
            return set()

        scoped: set[str] = set()
        pattern = f"comments_{platform}_{tenant_id}_*.json"
        for path in sorted(root.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            file_belongs = self._report_payload_belongs_to_job(
                data,
                job_id=job_id,
                content_ids=content_ids,
                task_keyword=task_keyword,
            )
            if not file_belongs:
                continue
            for row in data.get("comments") or []:
                if not isinstance(row, dict):
                    continue
                if not self._comment_row_belongs_to_job(row, job_id=job_id, file_belongs=True):
                    continue
                comment_id = str(row.get("comment_id") or "").strip()
                if not comment_id:
                    continue
                if candidate_ids is not None and comment_id not in candidate_ids:
                    continue
                scoped.add(comment_id)
        return scoped

    def _job_content_ids(self, job: AgentAsyncJob, supervisor_state: dict[str, Any]) -> set[str]:
        content_ids = {
            str(x).strip()
            for key in ("job_content_ids", "watched_content_ids")
            for x in (supervisor_state.get(key) or [])
            if str(x).strip()
        }
        result = job.result if isinstance(job.result, dict) else {}
        for cycle in result.get("supervisor_cycles") or []:
            if not isinstance(cycle, dict):
                continue
            params = cycle.get("params") if isinstance(cycle.get("params"), dict) else {}
            content_id = str(params.get("content_id") or "").strip()
            if content_id:
                content_ids.add(content_id)
        return content_ids

    def _job_scoped_comment_ids(
        self,
        job: AgentAsyncJob,
        supervisor_state: dict[str, Any],
        outreach_events: list[dict[str, Any]],
        *,
        db_session: Session,
    ) -> set[str] | None:
        job_id = str(job.job_id or "").strip()
        platform = str(job.platform or "douyin")
        content_ids = self._job_content_ids(job, supervisor_state)
        task_keyword = self._task_keyword(job)

        scoped: set[str] = set()
        for key in ("job_persisted_comment_ids", "job_evaluation_comment_ids"):
            raw = supervisor_state.get(key)
            if isinstance(raw, list):
                scoped.update(str(x).strip() for x in raw if str(x).strip())

        for event in outreach_events:
            if not isinstance(event, dict):
                continue
            comment_id = str(event.get("comment_id") or "").strip()
            if comment_id:
                scoped.add(comment_id)

        scoped |= self._comment_ids_from_reports_for_job(
            tenant_id=job.tenant_id,
            platform=platform,
            job_id=job_id,
            content_ids=content_ids,
            task_keyword=task_keyword,
        )

        evaluation_cache = supervisor_state.get("evaluation_cache")
        explicit_eval = supervisor_state.get("job_evaluation_comment_ids")
        has_explicit_eval = isinstance(explicit_eval, list) and bool(explicit_eval)
        if isinstance(evaluation_cache, dict) and evaluation_cache and not has_explicit_eval:
            eval_ids = {str(k).strip() for k in evaluation_cache if str(k).strip()}
            if eval_ids:
                from app.repositories.content_comment_repository import ContentCommentRepository

                repo = ContentCommentRepository(db_session, job.tenant_id)
                for row in repo.list_by_comment_ids(
                    platform=platform,
                    comment_ids=sorted(eval_ids),
                    limit=500,
                ):
                    row_content_id = str(row.content_id or "").strip()
                    if content_ids and row_content_id and row_content_id not in content_ids:
                        continue
                    if job_id and not self._content_comment_belongs_to_job(row, job_id):
                        raw = row.raw_data if isinstance(row.raw_data, dict) else {}
                        meta = raw.get("_agent_meta") if isinstance(raw.get("_agent_meta"), dict) else {}
                        if str(meta.get("source_job_id") or "").strip():
                            continue
                    scoped.add(str(row.comment_id))
                if not content_ids:
                    scoped |= self._comment_ids_from_reports_for_job(
                        tenant_id=job.tenant_id,
                        platform=platform,
                        job_id=job_id,
                        content_ids=content_ids,
                        task_keyword=task_keyword,
                        candidate_ids=eval_ids,
                    )

        if content_ids and job_id:
            from app.repositories.content_comment_repository import ContentCommentRepository

            repo = ContentCommentRepository(db_session, job.tenant_id)
            rows = repo.list_by_content_ids(
                platform=platform,
                content_ids=sorted(content_ids),
            )
            for row in rows:
                if self._content_comment_belongs_to_job(row, job_id):
                    scoped.add(str(row.comment_id))

        if scoped:
            return scoped

        if isinstance(evaluation_cache, dict) and evaluation_cache:
            evaluated_ids = {str(k).strip() for k in evaluation_cache if str(k).strip()}
            report_scoped = self._comment_ids_from_reports_for_job(
                tenant_id=job.tenant_id,
                platform=platform,
                job_id=job_id,
                content_ids=content_ids,
                task_keyword=task_keyword,
                candidate_ids=evaluated_ids,
            )
            if report_scoped:
                return report_scoped
            if evaluated_ids and not content_ids:
                return evaluated_ids

        if content_ids:
            return set()
        return None

    def _sandbox_payload(self, job: AgentAsyncJob) -> dict[str, Any]:
        sandbox = TaskSandboxService(self.settings, job.tenant_id)
        manifest = sandbox.load_manifest(job.job_id)
        conn = sandbox.connect(job.job_id)
        if manifest is None or conn is None:
            return {"available": False, "summary": {}, "leads": [], "outreach_events": [], "crawl_batches": []}
        try:
            return {
                "available": True,
                "summary": self._summary(conn, manifest),
                "leads": self._rows(conn, "leads", limit=500),
                "outreach_events": self._rows(conn, "outreach_events", limit=500),
                "crawl_batches": self._rows(conn, "crawl_batches", limit=100),
            }
        finally:
            conn.close()

    def _summary(self, conn: sqlite3.Connection, manifest: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "job_id": manifest.get("job_id"),
            "tables": list(manifest.get("tables") or []),
            "leads_total": self._count(conn, "leads"),
            "outreach_ok": self._count(conn, "outreach_events", "status = 'ok'"),
            "outreach_failed": self._count(conn, "outreach_events", "status = 'failed'"),
            "crawl_batches": self._count(conn, "crawl_batches"),
            "crawl_comments_total": 0,
        }
        try:
            row = conn.execute("SELECT COALESCE(SUM(comments_captured), 0) FROM crawl_batches WHERE status = 'ok'").fetchone()
            summary["crawl_comments_total"] = int(row[0] if row else 0)
        except sqlite3.Error:
            pass
        return summary

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str, where: str | None = None) -> int:
        try:
            sql = f"SELECT COUNT(*) FROM {table}"
            if where:
                sql = f"{sql} WHERE {where}"
            return int(conn.execute(sql).fetchone()[0])
        except sqlite3.Error:
            return 0

    @staticmethod
    def _rows(conn: sqlite3.Connection, table: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            cur = conn.execute(f"SELECT * FROM {table} ORDER BY id ASC LIMIT ?", (limit,))
            names = [d[0] for d in cur.description or []]
            return [dict(zip(names, row, strict=False)) for row in cur.fetchall()]
        except sqlite3.Error:
            return []
