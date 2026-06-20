from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.agent_experience import (
    AgentExperienceCreate,
    AgentExperienceOut,
    AgentExperienceUpdate,
    ExperienceScope,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    tokens: set[str] = set()
    for part in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_/-]{2,}", text.lower()):
        tokens.add(part)
    return tokens


class AgentExperienceStore:
    MAX_EXPERIENCES = 120

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _path_for(self, tenant_id: str):
        safe = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / safe / "experiences.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_raw(self, tenant_id: str) -> dict:
        path = self._path_for(tenant_id)
        if not path.exists():
            return {"dreamed_run_ids": [], "experiences": []}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"dreamed_run_ids": [], "experiences": []}
        raw.setdefault("dreamed_run_ids", [])
        raw.setdefault("experiences", [])
        return raw

    def _save_raw(self, tenant_id: str, payload: dict) -> None:
        path = self._path_for(tenant_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _to_out(self, raw: dict) -> AgentExperienceOut:
        data = dict(raw)
        data["scope"] = "tenant"
        return AgentExperienceOut.model_validate(data)

    def list_all(self, tenant_id: str, *, include_disabled: bool = True) -> list[AgentExperienceOut]:
        raw = self._load_raw(tenant_id)
        items = [self._to_out(item) for item in raw.get("experiences", [])]
        if not include_disabled:
            items = [item for item in items if item.enabled]
        return sorted(items, key=lambda x: x.updated_at or x.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    def get(self, tenant_id: str, experience_id: str) -> AgentExperienceOut | None:
        for item in self.list_all(tenant_id, include_disabled=True):
            if item.id == experience_id:
                return item
        return None

    def has_dreamed_run(self, tenant_id: str, run_id: str) -> bool:
        raw = self._load_raw(tenant_id)
        return run_id in set(raw.get("dreamed_run_ids") or [])

    def mark_dreamed_run(self, tenant_id: str, run_id: str) -> None:
        raw = self._load_raw(tenant_id)
        dreamed = list(raw.get("dreamed_run_ids") or [])
        if run_id not in dreamed:
            dreamed.append(run_id)
        raw["dreamed_run_ids"] = dreamed[-500:]
        self._save_raw(tenant_id, raw)

    def create(self, tenant_id: str, payload: AgentExperienceCreate) -> AgentExperienceOut:
        raw = self._load_raw(tenant_id)
        experiences = list(raw.get("experiences") or [])
        if any(item.get("id") == payload.id for item in experiences):
            raise ValueError(f"经验 ID 已存在: {payload.id}")
        # 简易去噪/版本化：同平台且关键词重合度高时，将新经验标记为旧经验的升级版本。
        new_kw = set(payload.task_keywords or [])
        for old in experiences[:30]:
            old_kw = set(old.get("task_keywords") or [])
            if not old_kw or not new_kw:
                continue
            overlap = len(new_kw & old_kw) / max(1, len(new_kw | old_kw))
            if overlap >= 0.6 and str(old.get("platform") or "") == str(payload.platform or ""):
                payload.version = int(old.get("version") or 1) + 1
                payload.supersedes_id = str(old.get("id") or "") or None
                if old.get("outcome") != payload.outcome:
                    payload.conflict_tag = "outcome_conflict"
                break
        now = _utc_now().isoformat()
        record = payload.model_dump()
        record["created_at"] = now
        record["updated_at"] = now
        experiences.insert(0, record)
        raw["experiences"] = experiences[: self.MAX_EXPERIENCES]
        self._save_raw(tenant_id, raw)
        return self._to_out(record)

    def update(self, tenant_id: str, experience_id: str, payload: AgentExperienceUpdate) -> AgentExperienceOut:
        raw = self._load_raw(tenant_id)
        experiences = list(raw.get("experiences") or [])
        updated: dict | None = None
        for idx, item in enumerate(experiences):
            if item.get("id") != experience_id:
                continue
            merged = dict(item)
            for key, value in payload.model_dump(exclude_none=True).items():
                merged[key] = value
            merged["updated_at"] = _utc_now().isoformat()
            experiences[idx] = merged
            updated = merged
            break
        if updated is None:
            raise KeyError(experience_id)
        raw["experiences"] = experiences
        self._save_raw(tenant_id, raw)
        return self._to_out(updated)

    def delete(self, tenant_id: str, experience_id: str) -> bool:
        raw = self._load_raw(tenant_id)
        experiences = list(raw.get("experiences") or [])
        new_items = [item for item in experiences if item.get("id") != experience_id]
        if len(new_items) == len(experiences):
            return False
        raw["experiences"] = new_items
        self._save_raw(tenant_id, raw)
        return True

    def retrieve_for_task(
        self,
        tenant_id: str,
        *,
        query: str,
        platform: str,
        limit: int = 5,
        agent_profile_id: str | None = None,
    ) -> list[AgentExperienceOut]:
        items = self.list_all(tenant_id, include_disabled=False)
        query_tokens = _tokenize(query)
        scored: list[tuple[float, AgentExperienceOut]] = []
        for item in items:
            if item.platform and item.platform != platform:
                continue
            if agent_profile_id:
                exp_profile = (item.agent_profile_id or "").strip()
                if exp_profile and exp_profile != agent_profile_id:
                    continue
            score = 0.0
            kw_tokens = _tokenize(" ".join(item.task_keywords))
            overlap = query_tokens & kw_tokens
            score += len(overlap) * 2.5
            for kw in item.task_keywords:
                if kw and kw.lower() in query.lower():
                    score += 4.0
            if item.outcome == "failure":
                score += 0.5
            if score <= 0:
                continue
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[: max(1, limit)]]

    def build_experience_prompt(
        self,
        tenant_id: str,
        *,
        query: str,
        platform: str,
        limit: int = 5,
        agent_profile_id: str | None = None,
    ) -> str:
        items = self.retrieve_for_task(
            tenant_id,
            query=query,
            platform=platform,
            limit=limit,
            agent_profile_id=agent_profile_id,
        )
        if not items:
            return ""
        lines = [
            "以下经验来自智能体「做梦」机制：对过往任务成功/失败记录的归纳。"
            "遇到相似场景时优先参考「建议做法」，并避开「应避免」。"
        ]
        for item in items:
            outcome_label = {"success": "成功", "failure": "失败", "partial": "部分成功"}.get(
                item.outcome, item.outcome
            )
            header = f"### [{outcome_label}] {item.title}"
            lines.append(header)
            lines.append(item.lesson.strip())
            if item.do_tips:
                lines.append("建议做法：")
                lines.extend(f"- {tip}" for tip in item.do_tips[:6])
            if item.avoid_tips:
                lines.append("应避免：")
                lines.extend(f"- {tip}" for tip in item.avoid_tips[:6])
        return "\n".join(lines)
