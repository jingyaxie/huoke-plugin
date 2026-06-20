from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.schemas.skill import SkillEffectDetailOut, SkillEffectStatsOut, SkillUsageRecordOut
from app.services.agent_run_store import AgentRunStore


def _score_from_result(status: str, has_error: bool) -> int:
    if status == "completed" and not has_error:
        return 92
    if status == "completed" and has_error:
        return 68
    if status in {"failed", "error"} or has_error:
        return 35
    return 60


_BLOCKED_HINTS = ("验证码", "风控", "登录", "拦截", "403", "429", "risk", "blocked", "异常")


def _blocked_reason(text: str) -> bool:
    blob = text.lower()
    return any(h.lower() in blob for h in _BLOCKED_HINTS)


class SkillEffectService:
    def __init__(self, run_store: AgentRunStore, tenant_id: str) -> None:
        self.run_store = run_store
        self.tenant_id = tenant_id

    def _extract_skill_id(self, tool_name: str, payload: dict[str, Any]) -> str | None:
        if tool_name.startswith("skill_"):
            return tool_name[len("skill_") :].replace("_", "-")
        if tool_name == "invoke_skill":
            sid = str(payload.get("skill_id") or "").strip()
            return sid or None
        sid = str(payload.get("skill_id") or "").strip()
        if sid:
            return sid
        return None

    def _parse_tool_payload(self, content: Any) -> dict[str, Any]:
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            try:
                data = json.loads(content)
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def list_skill_records(self, skill_id: str, *, limit: int = 20) -> list[SkillUsageRecordOut]:
        runs = self.run_store.list_for_tenant(self.tenant_id, limit=200)
        out: list[SkillUsageRecordOut] = []
        for run in runs:
            for msg in run.messages:
                if msg.get("role") != "tool":
                    continue
                tool_name = str(msg.get("tool_name") or msg.get("name") or "")
                data = self._parse_tool_payload(msg.get("content"))
                sid = self._extract_skill_id(tool_name, data)
                if sid != skill_id:
                    continue
                has_error = bool(data.get("error"))
                raw_status = str(data.get("status") or "").strip().lower()
                if raw_status in {"ready", "ok", "success"}:
                    status = "completed"
                elif raw_status:
                    status = raw_status
                else:
                    status = "failed" if has_error else "completed"
                reason = str(data.get("error") or data.get("reason") or "").strip()
                summary = str(data.get("summary") or "").strip()
                if not reason:
                    reason = "执行成功" if status == "completed" and not has_error else "执行失败"
                intercepted = _blocked_reason(reason) or _blocked_reason(summary)
                out.append(
                    SkillUsageRecordOut(
                        run_id=run.run_id,
                        timestamp=run.updated_at or run.created_at,
                        status=status,
                        score=_score_from_result(status, has_error),
                        reason=reason[:300],
                        tool_name=tool_name,
                        summary=summary[:300],
                    )
                )
                out[-1].__dict__["intercepted"] = intercepted
        out.sort(
            key=lambda x: x.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return out[: max(1, limit)]

    def get_skill_detail(self, skill_id: str, *, limit: int = 20) -> SkillEffectDetailOut:
        records = self.list_skill_records(skill_id, limit=limit)
        total = len(records)
        success = sum(1 for r in records if r.status == "completed")
        failed = total - success
        blocked = sum(1 for r in records if getattr(r, "intercepted", False))
        avg = round(sum(r.score for r in records) / total, 1) if total else 0.0
        blocked_rate = round((blocked / total) * 100, 1) if total else 0.0
        risk_level = "high" if blocked_rate >= 50 else "medium" if blocked_rate >= 20 else "low"
        stats = SkillEffectStatsOut(
            skill_id=skill_id,
            total=total,
            success=success,
            failed=failed,
            success_rate=round((success / total) * 100, 1) if total else 0.0,
            average_score=avg,
            last_score=records[0].score if records else None,
            blocked=blocked,
            blocked_rate=blocked_rate,
            risk_level=risk_level,
        )
        return SkillEffectDetailOut(skill_id=skill_id, stats=stats, records=records)
