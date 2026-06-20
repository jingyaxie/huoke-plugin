from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.agent_rule import AgentRuleCreate, AgentRuleOut, AgentRuleUpdate, RuleScope

DEFAULT_GLOBAL_RULES: list[dict] = [
    {
        "id": "browser-safety",
        "name": "浏览器操作安全",
        "description": "所有平台通用的浏览器自动化安全约束",
        "content": (
            "- 不要提交密码、验证码等敏感信息到非目标站点\n"
            "- 遇到登录墙或验证码时调用 task_failed 并说明需要人工介入\n"
            "- 每次写入操作前确认 selector 正确，避免误点"
        ),
        "always_apply": True,
        "platforms": [],
        "enabled": True,
        "scope": "global",
    },
    {
        "id": "douyin-platform",
        "name": "抖音平台规则",
        "description": "操作 douyin.com 时的额外约束",
        "content": (
            "- 优先使用 douyin.com 域名页面\n"
            "- 【Agent 禁止手工搜索】禁止 browser_goto /search/、/aisearch，禁止 browser_click/fill 点搜索框\n"
            "- 关键词+评论：只 invoke_skill douyin-keyword-comments 或 pipeline-keyword-video-comments；"
            "builtin 失败可加 show_browser=true 重试，勿改用手动点页面\n"
            "- 仅搜视频：search-content；仅抓单条评论：content-comments；回复评论：reply-comment\n"
            "- Recovery 诊断才用 browser_get_network_data(url_contains=search/item)，非日常主路径"
        ),
        "always_apply": True,
        "platforms": ["douyin"],
        "enabled": True,
        "scope": "global",
    },
    {
        "id": "douyin-social-actions",
        "name": "抖音社交互动安全",
        "description": "回复评论、关注、私信等写入操作的约束",
        "content": (
            "- 回复/关注/私信类技能仅通过 /skill-id 或 invoke_skill 显式调用，不要擅自批量操作\n"
            "- 执行前确认已登录；未登录时 task_failed，提示用户先完成登录\n"
            "- 每次任务只操作一个用户或一条评论；发送前核对 {{reply_text}} / {{message}} 内容\n"
            "- 遇到验证码、频率限制、私信权限不足时 task_failed 并说明，不要重复点击\n"
            "- 操作完成后用 browser_get_text 或 browser_get_page_info 验证结果再 task_complete"
        ),
        "always_apply": True,
        "platforms": ["douyin"],
        "enabled": True,
        "scope": "global",
    },
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentRuleStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.global_path = settings.storage_root / "rules" / "global.json"
        self.global_path.parent.mkdir(parents=True, exist_ok=True)

    def _tenant_path(self, tenant_id: str) -> Path:
        safe = normalize_tenant_id(tenant_id)
        path = self.settings.storage_root / "tenants" / safe / "rules.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_global_defaults(self) -> None:
        if self.global_path.exists():
            return
        now = _utc_now().isoformat()
        payload = {
            "rules": [{**r, "created_at": now, "updated_at": now} for r in DEFAULT_GLOBAL_RULES]
        }
        self.global_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_raw(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        rules = raw.get("rules", raw if isinstance(raw, list) else [])
        if not isinstance(rules, list):
            raise ValueError("rules 必须是数组")
        return rules

    def _to_out(self, raw: dict, scope: RuleScope) -> AgentRuleOut:
        data = {k: v for k, v in raw.items() if k not in {"created_at", "updated_at"}}
        data["scope"] = scope
        return AgentRuleOut.model_validate(data)

    def list_all(self, tenant_id: str, platform: str | None = None) -> list[AgentRuleOut]:
        self._ensure_global_defaults()
        merged: dict[str, AgentRuleOut] = {}
        for raw in self._load_raw(self.global_path):
            merged[raw["id"]] = self._to_out(raw, "global")
        for raw in self._load_raw(self._tenant_path(tenant_id)):
            merged[raw["id"]] = self._to_out(raw, "tenant")
        items = list(merged.values())
        if platform:
            items = [
                r
                for r in items
                if r.enabled and (not r.platforms or platform in r.platforms)
            ]
        else:
            items = [r for r in items if r.enabled]
        return sorted(items, key=lambda r: (r.scope != "global", r.name))

    def list_applicable(self, tenant_id: str, platform: str) -> list[AgentRuleOut]:
        rules = self.list_all(tenant_id, platform=platform)
        return [r for r in rules if r.always_apply]

    def get(self, tenant_id: str, rule_id: str) -> AgentRuleOut | None:
        for rule in self.list_all(tenant_id):
            if rule.id == rule_id:
                return rule
        return None

    def create(self, tenant_id: str, payload: AgentRuleCreate) -> AgentRuleOut:
        path = self._tenant_path(tenant_id)
        rules = self._load_raw(path)
        if any(r.get("id") == payload.id for r in rules):
            raise ValueError(f"规则 ID 已存在: {payload.id}")
        now = _utc_now().isoformat()
        record = payload.model_dump()
        record["scope"] = "tenant"
        record["created_at"] = now
        record["updated_at"] = now
        rules.append(record)
        path.write_text(json.dumps({"rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(record, "tenant")

    def update(self, tenant_id: str, rule_id: str, payload: AgentRuleUpdate) -> AgentRuleOut:
        rule = self.get(tenant_id, rule_id)
        if rule is None:
            raise KeyError(rule_id)
        if rule.scope == "global":
            raise ValueError("不能修改全局规则，请创建同名租户规则覆盖")
        path = self._tenant_path(tenant_id)
        rules = self._load_raw(path)
        updated: dict | None = None
        for idx, raw in enumerate(rules):
            if raw.get("id") != rule_id:
                continue
            merged = dict(raw)
            for key, value in payload.model_dump(exclude_none=True).items():
                merged[key] = value
            merged["updated_at"] = _utc_now().isoformat()
            rules[idx] = merged
            updated = merged
            break
        if updated is None:
            raise KeyError(rule_id)
        path.write_text(json.dumps({"rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._to_out(updated, "tenant")

    def delete(self, tenant_id: str, rule_id: str) -> bool:
        rule = self.get(tenant_id, rule_id)
        if rule is None or rule.scope == "global":
            return False
        path = self._tenant_path(tenant_id)
        rules = self._load_raw(path)
        new_rules = [r for r in rules if r.get("id") != rule_id]
        if len(new_rules) == len(rules):
            return False
        path.write_text(json.dumps({"rules": new_rules}, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def build_rules_prompt(
        self,
        tenant_id: str,
        platform: str,
        *,
        exclude_rule_ids: list[str] | None = None,
    ) -> str:
        applicable = self.list_applicable(tenant_id, platform)
        if exclude_rule_ids:
            excluded = set(exclude_rule_ids)
            applicable = [r for r in applicable if r.id not in excluded]
        if not applicable:
            return ""
        parts = []
        for rule in applicable:
            header = f"### {rule.name}"
            if rule.description:
                header += f" ({rule.description})"
            parts.append(f"{header}\n{rule.content.strip()}")
        return "\n\n".join(parts)
