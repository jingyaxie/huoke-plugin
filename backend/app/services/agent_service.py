from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any, Literal

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.antibot import AntibotContext, headless_for_platform
from app.platforms.constants import PLATFORM_LABELS
from app.platforms.registry import get_session_store
from app.schemas.agent import AgentEvent, AgentMode, RunMode
from app.services.agent_browser_session import AgentBrowserSession, AgentSessionManager
from app.services.agent_checkpoint_store import AgentCheckpointStore
from app.services.agent_policy import (
    ASK_MODE_PROMPT,
    PLAN_MODE_PROMPT,
    SPAWN_TASK_TOOL,
    filter_tools_for_mode,
    is_write_tool,
    requires_approval,
    tool_needs_browser,
)
from app.services.agent_run_controller import AgentRunController
from app.services.agent_dream_service import AgentDreamService
from app.services.agent_experience_store import AgentExperienceStore
from app.services.agent_profile_store import AgentProfileStore
from app.services.agent_rule_store import AgentRuleStore
from app.schemas.agent_profile import AgentProfileOut
from app.services.agent_session_binding import bind_session_sandbox
from app.services.agent_network_capture import compact_tool_result_for_llm
from app.services.agent_run_store import (
    AgentRunRecord,
    AgentRunStore,
    LoopState,
    PendingApproval,
    PendingPlan,
    parse_explicit_skill_ids,
    sanitize_message_for_storage,
    trim_history,
)
from app.services.ai_client import AIClientFactory
from app.services.playwright_tools import (
    TOOL_DEFINITIONS,
    PlaywrightToolExecutor,
    parse_tool_arguments,
)
from app.services.skill_executor import (
    SkillExecutor,
    build_skill_tool_definitions,
    skills_description_summary,
)
from app.services.skill_auto_install import auto_install_from_message
from app.services.skillhub_installer import SkillHubInstaller
from app.services.skillhub_package import read_package_file, run_package_script
from app.services.skillhub_tools import build_skillhub_tool_definitions
from app.services.skill_store import SkillStore
from app.services.skill_effect_service import SkillEffectService
from app.services.agent_result_validator import build_validation_report
from app.services.agent_llm import (
    AssistantTurn,
    maybe_compress_history,
    prepare_messages_for_provider,
    repair_messages_tool_responses,
    resolve_default_provider,
    stream_chat_completion,
    trim_assistant_tool_call,
)
from app.services.agent_subagent import run_subagent
from app.services.comment_data_service import (
    analyze_comment_leads,
    collect_comment_files_from_history,
    list_comment_files,
    read_comment_file,
)
from app.services.comment_data_tools import COMMENT_DATA_TOOL_DEFINITIONS
from app.services.stored_comment_service import StoredCommentService
from app.services.stored_comment_tools import (
    STORED_COMMENT_READ_TOOLS,
    STORED_COMMENT_TOOL_DEFINITIONS,
    STORED_COMMENT_TOOL_NAMES,
    STORED_COMMENT_WRITE_TOOLS,
)
RUNTIME_KERNEL_PROMPT = """你是一个浏览器自动化智能体。

【底层】BrowserRuntime（browser_* 工具）
- 真实 Chrome + 人类延迟/滚动（browser_warmup、browser_browse）
- 自动拦截 XHR/Fetch JSON（browser_wait_api、browser_get_network_data）
- 底层只提供浏览能力，业务由 Skill 或档案任务说明决定

【业务层】Skill
- 业务能力通过 invoke_skill / skill_* 调用；具体可用 Skill 见文末摘要与档案限定
- SkillHub：skillhub_search / skillhub_install / read_skill_resource / run_skill_script

可用 browser 工具：browser_goto、browser_browse、browser_warmup、browser_wait_api、browser_get_network_data、browser_click、browser_fill、browser_scroll、browser_get_page_info、browser_screenshot

通用约束：
- 复杂子任务用 spawn_task；成功 task_complete，失败 task_failed
- 不要编造未观察到的数据
- 登录墙/验证码 → task_failed
- 优先复用历史 tool 返回与已拦截 JSON
- 回复使用中文
"""

STANDARD_WORKFLOW_PROMPT = """【标准获客流程】（仅当档案未指定专用链路时适用）

builtin Skill：*-keyword-comments、content-comments、search-content、follow-user、send-dm、reply-comment、pipeline-keyword-video-comments、query-stored-comments、query-interaction-stats、check-login

Pipeline：/pipeline-keyword-video-comments（T0 builtin → T1 show_browser 重试 → T2 Agent Recovery）

builtin 失败兜底（禁止改用手动点页面完成业务）：
1. check-login，未登录则 task_failed
2. 同一 builtin 加 show_browser=true 重试
3. 仍失败则 task_failed；可用 browser_get_page_info 诊断，禁止 browser_click/fill 模拟搜索/翻评论

工作方式：
1. list_skills → 优先 invoke 对应 builtin
2. 关键词+评论：douyin-keyword-comments / xhs-keyword-comments / pipeline-keyword-video-comments
3. 关注/私信/回复：follow-user / send-dm / reply-comment（勿 browser 翻页找评论）
4. 【数据库 content_comments】查：query_stored_contents / query_stored_comments / get_stored_content_detail / get_stored_comment；增删改用 create/update/delete_stored_*
5. 【本地 JSON】仅分析磁盘 reports/*.json：list_local_comment_files / read_local_comments / analyze_local_comments
6. 回复评论：reply-comment（comment_id、content_url、reply_to_user_id、photo_author_id）

抖音关键词+评论/搜索：只 invoke douyin-keyword-comments / search-content / pipeline，禁止 browser 点搜索框或 goto /search/
"""

# 兼容旧引用
SYSTEM_PROMPT = RUNTIME_KERNEL_PROMPT + "\n\n" + STANDARD_WORKFLOW_PROMPT


def _build_system_prompt(
    skills_summary: str,
    rules_prompt: str,
    experience_prompt: str,
    mode: AgentMode,
    profile: AgentProfileOut | None = None,
) -> str:
    profile = profile or AgentProfileStore.default_profile()
    custom = (profile.system_prompt or "").strip()
    parts: list[str] = []
    if profile.inherit_base_prompt:
        parts.append(RUNTIME_KERNEL_PROMPT)
        if profile.inherit_workflow_prompt:
            parts.append(STANDARD_WORKFLOW_PROMPT)
        if custom:
            parts.append(f"## 角色与任务（{profile.name}）\n{custom}")
    elif custom:
        parts = [custom]
    else:
        parts.append(RUNTIME_KERNEL_PROMPT)
        if profile.inherit_workflow_prompt:
            parts.append(STANDARD_WORKFLOW_PROMPT)
    if mode == "plan":
        parts.append(PLAN_MODE_PROMPT)
    elif mode == "ask":
        parts.append(ASK_MODE_PROMPT)
    if experience_prompt:
        parts.append(f"## 历史经验（做梦归纳）\n{experience_prompt}")
    if rules_prompt:
        parts.append(f"## 租户规则\n{rules_prompt}")
    if skills_summary:
        parts.append(f"可用技能摘要（完整内容在 invoke_skill 时加载）：\n{skills_summary}")
    return "\n\n".join(parts)


def _apply_system_prompt_to_messages(
    messages: list[dict[str, Any]],
    content: str,
) -> None:
    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": content}
    else:
        messages.insert(0, {"role": "system", "content": content})


def _has_image_content(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


class AgentService:
    _repeat_guard_window = 8
    _repeat_guard_threshold = 3
    _failure_help_threshold = 2

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        platform: str,
        db_session: Session | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.account_id = account_id
        self.db_session = db_session
        self.session_manager = AgentSessionManager.get_instance()
        self.run_store = AgentRunStore(settings)
        self.rule_store = AgentRuleStore(settings)
        self.profile_store = AgentProfileStore(settings)
        self.checkpoint_store = AgentCheckpointStore(settings)
        self.run_controller = AgentRunController.get()
        self.ai_factory = AIClientFactory(settings)
        self.skill_store = SkillStore(settings)
        self.experience_store = AgentExperienceStore(settings)
        self._active_comment_file_refs: list[str] = []

    def _dream_service(self) -> AgentDreamService:
        return AgentDreamService(self.settings, self.tenant_id)

    def platform_binding_status(self) -> dict[str, Any]:
        """当前租户+账号+平台的登录绑定状态，供 API 预检与错误提示。"""
        store = get_session_store(self.settings, self.platform)
        status = store.login_status(self.tenant_id, self.account_id)
        platform_label = PLATFORM_LABELS.get(self.platform, self.platform)
        binding_status = str(status.get("status") or "missing")
        ready = binding_status == "ready"
        default_messages = {
            "missing": f"账号「{self.account_id}」尚未绑定{platform_label}，请先完成平台登录后再调用智能体。",
            "incomplete": f"{platform_label} 登录态不完整（账号 {self.account_id}），请重新扫码绑定。",
            "error": str(status.get("message") or "读取登录态失败"),
        }
        message = (
            str(status.get("message") or "")
            if ready
            else default_messages.get(binding_status, default_messages["missing"])
        )
        payload: dict[str, Any] = {
            "ready": ready,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "platform": self.platform,
            "platform_label": platform_label,
            "status": binding_status,
            "message": message,
            "cookie_count": int(status.get("cookie_count") or 0),
            "storage_state_path": status.get("storage_state_path"),
        }
        if not ready:
            payload.update(
                {
                    "code": "binding_required",
                    "bind_api": (
                        f"/api/accounts/{self.account_id}/platforms/{self.platform}/server-login"
                    ),
                    "bindings_api": f"/api/accounts/{self.account_id}/bindings",
                }
            )
        return payload

    def binding_required_error(self) -> dict[str, Any] | None:
        ctx = AntibotContext.for_tenant(self.settings, self.tenant_id)
        if not ctx.require_login:
            return None
        status = self.platform_binding_status()
        if status.get("ready"):
            return None
        return status

    async def _maybe_auto_dream(
        self,
        run_id: str,
        *,
        summary: str = "",
        provider: str | None = None,
    ) -> None:
        if not self.settings.agent_dream_enabled or not self.settings.agent_dream_auto:
            return
        client, model = self._resolve_client(provider or resolve_default_provider(self.settings))
        try:
            await self._dream_service().dream_from_run(
                run_id,
                summary=summary,
                use_llm=self.settings.agent_dream_use_llm,
                client=client,
                model=model,
            )
        except Exception:
            pass

    def _resolve_client(self, provider: str) -> tuple[AsyncOpenAI | None, str | None]:
        return self.ai_factory.deepseek(), self.settings.deepseek_model

    def _resolve_vision_model(self, provider: str, default_model: str) -> str | None:
        return None

    @staticmethod
    def _normalize_tool_args(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(k): AgentService._normalize_tool_args(value[k])
                for k in sorted(value.keys(), key=str)
            }
        if isinstance(value, list):
            return [AgentService._normalize_tool_args(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _tool_call_fingerprint(self, fn_name: str, fn_args: dict[str, Any]) -> str:
        normalized = self._normalize_tool_args(fn_args)
        payload = {"tool": fn_name, "args": normalized}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _tool_budget_limit(self, category: str) -> int:
        limits = {
            "read": max(10, int(getattr(self.settings, "agent_budget_read", 80))),
            "write": max(5, int(getattr(self.settings, "agent_budget_write", 30))),
            "skill": max(5, int(getattr(self.settings, "agent_budget_skill", 30))),
            "control": max(5, int(getattr(self.settings, "agent_budget_control", 20))),
        }
        return limits.get(category, 20)

    @staticmethod
    def _tool_category(fn_name: str) -> str:
        if fn_name.startswith("skill_") or fn_name in {
            "invoke_skill",
            "list_skills",
            "skillhub_search",
            "skillhub_install",
            "read_skill_resource",
            "run_skill_script",
        }:
            return "skill"
        if fn_name in {"task_complete", "task_failed", "submit_plan", "spawn_task", "submit_execution_plan", "mark_step_done"}:
            return "control"
        if fn_name in STORED_COMMENT_WRITE_TOOLS:
            return "write"
        if fn_name in STORED_COMMENT_READ_TOOLS:
            return "read"
        if fn_name.startswith("browser_click") or fn_name.startswith("browser_fill") or fn_name.startswith("browser_type"):
            return "write"
        if fn_name.startswith("browser_"):
            return "read"
        return "read"

    @staticmethod
    def _classify_failure(result: dict[str, Any]) -> str | None:
        status = str(result.get("status") or "").lower()
        text = (
            f"{result.get('error') or ''} {result.get('reason') or ''} "
            f"{result.get('summary') or ''}"
        ).lower()
        if status not in {"failed", "error"} and not result.get("error"):
            return None
        if any(k in text for k in ("验证码", "风控", "risk", "blocked", "429", "403")):
            return "risk_control"
        if any(k in text for k in ("登录", "login", "cookie", "storage_state")):
            return "login_required"
        if any(k in text for k in ("timeout", "超时", "未找到", "not found", "selector")):
            return "page_changed"
        if any(k in text for k in ("empty", "无数据", "no data", "列表为空")):
            return "empty_data"
        if any(
            k in text
            for k in (
                "missing",
                "positional argument",
                "typeerror",
                "attributeerror",
                "技能不存在",
            )
        ):
            return "skill_internal_error"
        return "generic_error"

    @staticmethod
    def _failure_guidance(failure_type: str) -> str:
        mapping = {
            "risk_control": "触发风控时不要继续点进视频，优先复用当前已抓到的列表 JSON（aweme_id）并改走单视频评论抓取链路。",
            "login_required": "登录态异常，请优先检查绑定状态/重新登录，再继续任务，避免重复无效调用。",
            "page_changed": "页面结构可能变化，优先改用 browser_get_page_info 或 browser_get_network_data 抓结构化数据。",
            "empty_data": "当前返回空数据，先确认关键词/时间范围是否过窄，并复用历史成功参数重试。",
            "skill_internal_error": (
                "builtin 执行异常：先 check-login，再同一 skill 加 show_browser=true 重试；"
                "若仍报错则 task_failed，禁止改用手动 browser 搜索/翻页。"
            ),
            "generic_error": (
                "连续失败：优先重试同一 builtin（可加 show_browser=true），"
                "勿改用手动 browser 点搜索框或翻评论区。"
            ),
        }
        return mapping.get(failure_type, mapping["generic_error"])

    @staticmethod
    def _skill_failure_recovery_message(
        fn_name: str,
        fn_args: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        skill_id = str(fn_args.get("skill_id") or "").strip()
        if not skill_id and fn_name.startswith("skill_"):
            skill_id = fn_name[len("skill_") :].replace("_", "-")
        params = fn_args if fn_name.startswith("skill_") else (fn_args.get("params") or {})
        if not isinstance(params, dict):
            params = {}
        show_browser = bool(params.get("show_browser"))
        err = str(result.get("error") or result.get("summary") or "").strip()
        lines = [
            "【Skill 执行失败】本任务应留在 builtin 层完成，禁止改用手动 browser 点搜索框、翻评论区。",
            "请严格按序：",
            "1) invoke check-login；未登录则 task_failed",
        ]
        if skill_id:
            if show_browser:
                lines.append(
                    f"2) 已对 {skill_id} 使用 show_browser 仍失败 → 直接 task_failed，附上错误：{err[:200]}"
                )
            else:
                lines.append(
                    f"2) 再次 invoke_skill skill_id={skill_id}，保留原 params 并加 show_browser=true"
                )
        else:
            lines.append("2) 同一 builtin 加 show_browser=true 重试")
        if any(k in err.lower() for k in ("missing", "typeerror", "attributeerror", "positional argument")):
            lines.append("3) 错误像服务端实现问题，勿用 browser_warmup/click/fill 兜底，应 task_failed 上报")
        else:
            lines.append("3) 勿用 browser_warmup + 搜索框模拟关键词搜索")
        return "\n".join(lines)

    @staticmethod
    def _should_block_manual_douyin_search_ui(
        *,
        platform: str,
        fn_name: str,
        fn_args: dict[str, Any],
    ) -> bool:
        if platform != "douyin":
            return False
        if fn_name not in {"browser_click", "browser_fill", "browser_press"}:
            return False
        selector = str(fn_args.get("selector") or fn_args.get("selector_hint") or "").lower()
        if "searchbar" in selector or "search-bar" in selector:
            return True
        if fn_name == "browser_fill" and str(fn_args.get("text") or fn_args.get("value") or "").strip():
            # 无 selector 时对搜索框 fill 的宽松拦截：仅当显式提到搜索
            if "search" in selector or "搜索" in selector:
                return True
        return False

    @staticmethod
    def _filter_skills_for_profile(skills: list[Any], profile: AgentProfileOut) -> list[Any]:
        if not profile.skill_ids:
            return skills
        allowed = set(profile.skill_ids)
        return [skill for skill in skills if skill.id in allowed]

    def _system_prompt_for_profile(
        self,
        profile: AgentProfileOut,
        skills: list[Any],
        explicit_skill_ids: set[str] | list[str],
        mode: AgentMode,
        *,
        user_query: str = "",
    ) -> str:
        rules_prompt = self.rule_store.build_rules_prompt(
            self.tenant_id,
            self.platform,
            exclude_rule_ids=profile.exclude_rule_ids,
        )
        experience_prompt = ""
        if self.settings.agent_dream_enabled and profile.inherit_experience_prompt:
            experience_prompt = self.experience_store.build_experience_prompt(
                self.tenant_id,
                query=user_query,
                platform=self.platform,
                limit=self.settings.agent_dream_inject_max,
                agent_profile_id=profile.id,
            )
        explicit = set(explicit_skill_ids or [])
        content = _build_system_prompt(
            skills_description_summary(skills, explicit),
            rules_prompt,
            experience_prompt,
            mode,
            profile,
        )
        return content

    def _prioritize_skills(self, skills: list[Any]) -> list[Any]:
        if not skills:
            return skills
        svc = SkillEffectService(self.run_store, self.tenant_id)
        score_map: dict[str, float] = {}
        for skill in skills:
            detail = svc.get_skill_detail(skill.id, limit=20)
            stats = detail.stats
            combined = (stats.average_score * 0.7) + (stats.success_rate * 0.3) - (stats.blocked_rate * 0.4)
            score_map[skill.id] = combined
        return sorted(skills, key=lambda s: score_map.get(s.id, 0.0), reverse=True)

    def _agent_meta_payload(
        self,
        *,
        tool_usage: dict[str, int] | None = None,
        failure_streak: dict[str, int] | None = None,
        skill_priority: list[str] | None = None,
    ) -> dict[str, Any]:
        budget_limits = {
            "read": self._tool_budget_limit("read"),
            "write": self._tool_budget_limit("write"),
            "skill": self._tool_budget_limit("skill"),
            "control": self._tool_budget_limit("control"),
        }
        return {
            "budget_limits": budget_limits,
            "tool_usage": dict(tool_usage or {}),
            "failure_streak": dict(failure_streak or {}),
            "skill_priority": list(skill_priority or []),
        }

    @staticmethod
    def _is_douyin_direct_search_url(url: str) -> bool:
        u = (url or "").lower()
        if "douyin.com" not in u:
            return False
        return "/search/" in u or "/aisearch" in u or "://www.douyin.com/search" in u

    @staticmethod
    def _should_block_douyin_direct_search(
        *,
        platform: str,
        fn_name: str,
        fn_args: dict[str, Any],
    ) -> bool:
        if platform != "douyin":
            return False
        if fn_name not in {"browser_goto", "browser_browse"}:
            return False
        return AgentService._is_douyin_direct_search_url(str(fn_args.get("url") or ""))

    @staticmethod
    def _should_block_redundant_search(
        *,
        fn_name: str,
        fn_args: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> bool:
        if not snapshot:
            return False
        has_video_evidence = bool(
            snapshot.get("aweme_id")
            or snapshot.get("video_id")
            or snapshot.get("video_url")
            or snapshot.get("url")
            or snapshot.get("videos_preview")
        )
        if not has_video_evidence:
            return False
        if fn_name in {"skill_search_videos"}:
            return True
        legacy_search = {"search-videos", "search-content"}
        if fn_name == "invoke_skill" and str(fn_args.get("skill_id") or "").strip() in legacy_search:
            return True
        if fn_name == "browser_goto":
            url = str(fn_args.get("url") or "").lower()
            if "search" in url:
                return True
        return False

    @staticmethod
    def _build_review_report(
        *,
        terminal_status: str,
        terminal_summary: str,
        tool_usage: dict[str, int],
        failure_streak: dict[str, int],
        task_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        total_tools = sum(int(v or 0) for v in tool_usage.values())
        top_failures = sorted(failure_streak.items(), key=lambda x: x[1], reverse=True)[:3]
        return {
            "status": terminal_status,
            "summary": terminal_summary[:300],
            "total_tools": total_tools,
            "tool_usage": dict(tool_usage),
            "top_failures": [{"type": k, "count": v} for k, v in top_failures],
            "snapshot_keys": sorted(list(task_snapshot.keys())),
            "advice": (
                "优先复用 task_snapshot 里的 aweme_id/video_url 继续抓取，避免重复关键词搜索。"
                if task_snapshot
                else "未形成结构化证据，建议先调用网络数据提取能力建立 task_snapshot。"
            ),
        }

    @staticmethod
    def _primary_user_goal(history: list[dict[str, Any]]) -> str:
        for msg in history:
            if msg.get("role") != "user":
                continue
            content = str(msg.get("content") or "").strip()
            if content and not content.startswith("【"):
                return content
        return ""

    @staticmethod
    def _is_douyin_skill(fn_name: str, fn_args: dict[str, Any]) -> bool:
        if fn_name in {
            "skill_search_content",
            "skill_content_comments",
            "skill_douyin_keyword_comments",
            "skill_xhs_keyword_comments",
            "skill_follow_user",
            "skill_send_dm",
        }:
            return True
        if fn_name == "invoke_skill":
            sid = str(fn_args.get("skill_id") or "").strip()
            return sid in {
                "search-content",
                "content-comments",
                "douyin-keyword-comments",
                "xhs-keyword-comments",
                "kuaishou-keyword-comments",
                "pipeline-keyword-video-comments",
                "follow-user",
                "send-dm",
                "reply-comment",
            }
        return False

    @staticmethod
    def _skill_context_mismatch(goal: str, fn_name: str, fn_args: dict[str, Any]) -> bool:
        if not AgentService._is_douyin_skill(fn_name, fn_args):
            return False
        text = goal.lower()
        douyin_hints = ("抖音", "douyin", "短视频", "视频评论", "热榜")
        finance_hints = (
            "黄金",
            "gold",
            "xau",
            "走势",
            "k线",
            "macd",
            "均线",
            "etf",
            "美联储",
            "利率",
            "通胀",
            "cpi",
            "非农",
            "外汇",
            "原油",
            "纳指",
            "标普",
            "a股",
        )
        if any(k in text for k in finance_hints) and not any(k in text for k in douyin_hints):
            return True
        return False

    @staticmethod
    def _extract_task_snapshot(history: list[dict[str, Any]], max_scan: int = 30) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for msg in reversed(history[-max_scan:]):
            if msg.get("role") != "tool":
                continue
            try:
                payload = json.loads(msg.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            for key in (
                "aweme_id",
                "video_id",
                "video_url",
                "url",
                "sec_uid",
                "author",
                "author_id",
                "title",
                "keyword",
            ):
                value = payload.get(key)
                if value and key not in snapshot:
                    snapshot[key] = value
            previews = payload.get("videos_preview")
            if isinstance(previews, list) and previews and "videos_preview" not in snapshot:
                snapshot["videos_preview"] = previews[:5]
        return snapshot

    def get_config(self) -> dict[str, Any]:
        default_provider = resolve_default_provider(self.settings)
        default_run_mode = self.settings.agent_default_run_mode
        if default_run_mode not in {"auto", "confirm"}:
            default_run_mode = "auto"
        return {
            "default_provider": default_provider,
            "default_run_mode": default_run_mode,
            "dream_enabled": self.settings.agent_dream_enabled,
            "dream_auto": self.settings.agent_dream_auto,
            "providers": {
                "deepseek": {
                    "configured": bool(self.settings.deepseek_api_key),
                    "vision": False,
                    "model": self.settings.deepseek_model,
                    "note": "不支持 Vision，截图后请用 browser_get_text 读取页面文字",
                },
            },
        }

    async def create_session(
        self,
        *,
        headless: bool | None = None,
        auto_start: bool = True,
    ) -> AgentBrowserSession:
        return await self.session_manager.create(
            self.tenant_id,
            self.platform,
            self.settings,
            account_id=self.account_id,
            headless=headless,
            auto_start=auto_start,
        )

    async def close_session(self, session_id: str) -> bool:
        return await self.session_manager.close(session_id)

    def get_run(self, run_id: str) -> AgentRunRecord | None:
        return self.run_store.get(self.tenant_id, run_id)

    def delete_run(self, run_id: str) -> bool:
        return self.run_store.delete(self.tenant_id, run_id)

    def list_runs(self, *, limit: int = 50):
        from app.services.agent_run_store import run_title_from_messages

        records = self.run_store.list_for_tenant(self.tenant_id, limit=limit)
        summaries = []
        for record in records:
            summaries.append(
                {
                    "run_id": record.run_id,
                    "title": run_title_from_messages(record.messages),
                    "status": record.status,
                    "message_count": len(record.messages),
                    "platform": record.platform,
                    "updated_at": record.updated_at,
                    "created_at": record.created_at,
                }
            )
        return summaries

    def list_checkpoints(self, run_id: str):
        return self.checkpoint_store.list_for_run(self.tenant_id, run_id)

    async def cancel_run(self, run_id: str) -> bool:
        registered = await self.run_controller.cancel(run_id)
        run = self.run_store.get(self.tenant_id, run_id)
        if run is None:
            return registered
        if run.status in {"completed", "failed"}:
            return registered
        if run.status != "interrupted":
            run.status = "interrupted"  # type: ignore[assignment]
            self.run_store.save(run)
        session = self.session_manager.get(run.browser_session_id)
        if session is not None:
            with contextlib.suppress(Exception):
                await session.close()
        return True

    def _is_run_cancelled(self, run_id: str) -> bool:
        return self.run_controller.is_cancelled(run_id)

    def _cancelled_tool_result(self) -> dict[str, Any]:
        return {"error": "用户已停止执行", "status": "cancelled"}

    async def _ensure_browser_with_cancel(
        self,
        session: AgentBrowserSession,
        run_id: str,
    ):
        if run_id and self._is_run_cancelled(run_id):
            return None
        if session.is_started:
            return session.page
        task = asyncio.create_task(session.ensure_started())
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=0.5)
                if task in done:
                    return task.result()
                if run_id and self._is_run_cancelled(run_id):
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
                    with contextlib.suppress(Exception):
                        await session.close()
                    return None
        except Exception:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            raise

    async def _execute_tool_with_cancel(
        self,
        run_id: str,
        execute: Any,
    ) -> dict[str, Any]:
        if run_id and self._is_run_cancelled(run_id):
            return self._cancelled_tool_result()

        task = asyncio.create_task(execute())
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=0.5)
                if task in done:
                    return task.result()
                if run_id and self._is_run_cancelled(run_id):
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    return self._cancelled_tool_result()
        except asyncio.CancelledError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            raise

    async def restore_checkpoint(self, run_id: str, checkpoint_id: str) -> dict[str, Any]:
        run = self.run_store.get(self.tenant_id, run_id)
        if run is None:
            raise ValueError("对话 Run 不存在")
        payload = self.checkpoint_store.load(self.tenant_id, run_id, checkpoint_id)
        if payload is None:
            raise ValueError("检查点不存在")
        session = self.session_manager.get(run.browser_session_id)
        if session is None:
            raise ValueError("浏览器会话已失效")
        await session.restore_from_checkpoint(
            payload["storage_state"],
            url=payload.get("url"),
        )
        info = await session.page_info()
        return {
            "checkpoint_id": checkpoint_id,
            "url": info["url"],
            "title": info["title"],
        }

    def _append_tools_for_mode(
        self,
        tools: list[dict[str, Any]],
        mode: AgentMode,
    ) -> list[dict[str, Any]]:
        if mode != "agent":
            return tools
        if any(t.get("function", {}).get("name") == "spawn_task" for t in tools):
            return tools
        return tools + [SPAWN_TASK_TOOL]

    async def _save_checkpoint_if_needed(
        self,
        *,
        run_id: str,
        step: int,
        tool: str,
        session: AgentBrowserSession,
    ):
        if not self.settings.agent_checkpoints_enabled or not is_write_tool(tool):
            return None
        if not session.is_started:
            return None
        info = await session.page_info()
        storage_state = await session.capture_storage_state()
        record = self.checkpoint_store.save(
            self.tenant_id,
            run_id,
            step=step,
            tool=tool,
            url=info.get("url"),
            title=info.get("title"),
            storage_state=storage_state,
        )
        self.checkpoint_store.trim(
            self.tenant_id,
            run_id,
            self.settings.agent_checkpoint_max_count,
        )
        return record

    def _persist_run(
        self,
        run: AgentRunRecord,
        history: list[dict[str, Any]],
        status: str,
    ) -> None:
        run.messages = [
            sanitize_message_for_storage(msg)
            for msg in trim_history(history, self.settings.agent_max_history_messages)
        ]
        run.status = status  # type: ignore[assignment]
        run.updated_at = None
        self.run_store.save(run)

    def _save_loop_checkpoint(
        self,
        run: AgentRunRecord,
        history: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        *,
        step: int,
        mode: AgentMode,
        run_mode: RunMode,
        status: str = "active",
        phase: str = "plan",
        explicit_skill_ids: list[str] | None = None,
    ) -> None:
        snapshot = self._extract_task_snapshot(history)
        run.loop_state = LoopState(
            messages=list(messages),
            history=list(history),
            step=step,
            provider=run.provider,
            agent_profile_id=run.agent_profile_id or "default",
            explicit_skill_ids=list(explicit_skill_ids or []),
            mode=mode,
            run_mode=run_mode,
            phase=phase,
            task_snapshot=snapshot,
        )
        self._persist_run(run, history, status)

    def _mark_run_interrupted(self, run_id: str) -> None:
        run = self.run_store.get(self.tenant_id, run_id)
        if run is None or run.loop_state is None:
            return
        if run.status in {"waiting_plan", "waiting_approval", "completed", "failed"}:
            return
        run.status = "interrupted"  # type: ignore[assignment]
        self.run_store.save(run)

    async def _execute_tool(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
        *,
        executor: PlaywrightToolExecutor,
        skill_executor: SkillExecutor,
        skills_by_tool: dict[str, Any],
        skills_by_id: dict[str, Any],
        mode: AgentMode,
    ) -> dict[str, Any] | None:
        if fn_name == "submit_plan":
            if mode != "plan":
                return {"error": "submit_plan 仅在 Plan 模式下可用"}
            return None

        if fn_name == "list_skills":
            items = self.skill_store.list_enabled(self.tenant_id)
            return {
                "skills": [
                    {
                        "id": s.id,
                        "tool_name": s.tool_name,
                        "name": s.name,
                        "description": s.description,
                        "type": s.type,
                        "manual_only": s.disable_model_invocation,
                    }
                    for s in items
                ]
            }

        if fn_name == "invoke_skill":
            from app.services.skill_store import resolve_skill_id

            skill_id = fn_args.get("skill_id")
            if not skill_id:
                return {"error": "缺少 skill_id"}
            skill = skills_by_id.get(resolve_skill_id(str(skill_id).strip()))
            if skill is None:
                return {"error": f"技能不存在或未启用: {skill_id}"}
            params = fn_args.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            return await skill_executor.execute(skill, params)

        if fn_name.startswith("skill_"):
            skill = skills_by_tool.get(fn_name)
            if skill is None:
                return {"error": f"技能工具不存在或未启用: {fn_name}"}
            return await skill_executor.execute(skill, fn_args)

        if fn_name == "spawn_task":
            return {"error": "spawn_task 由智能体循环直接处理"}

        comment_result = self._execute_comment_data_tool(fn_name, fn_args)
        if comment_result is not None:
            return comment_result

        stored_result = self._execute_stored_comment_tool(fn_name, fn_args)
        if stored_result is not None:
            return stored_result

        hub_result = await self._execute_skillhub_tool(fn_name, fn_args, skills_by_id=skills_by_id)
        if hub_result is not None:
            return hub_result

        result, _ = await executor.execute(fn_name, fn_args)
        return result

    def _execute_comment_data_tool(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        if fn_name == "list_local_comment_files":
            limit = int(fn_args.get("limit") or 20)
            files = list_comment_files(
                self.settings,
                tenant_id=self.tenant_id,
                platform=self.platform,
                limit=min(limit, 50),
            )
            return {"files": files, "count": len(files)}

        if fn_name == "read_local_comments":
            file_name = str(fn_args.get("file_name") or "").strip()
            if not file_name:
                return {"error": "缺少 file_name"}
            max_comments = int(fn_args.get("max_comments") or 200)
            return read_comment_file(
                self.settings,
                file_name,
                max_comments=min(max_comments, 500),
            )

        if fn_name == "analyze_local_comments":
            file_names = fn_args.get("file_names") or []
            if not isinstance(file_names, list):
                file_names = []
            refs = [str(x) for x in file_names if x]
            if not refs:
                refs = list(getattr(self, "_active_comment_file_refs", None) or [])
            intent_keywords = fn_args.get("intent_keywords") or []
            if not isinstance(intent_keywords, list):
                intent_keywords = []
            max_leads = int(fn_args.get("max_leads") or 80)
            return analyze_comment_leads(
                self.settings,
                file_refs=refs,
                tenant_id=self.tenant_id,
                platform=self.platform,
                intent_keywords=[str(x) for x in intent_keywords if x],
                max_leads=min(max_leads, 200),
            )

        return None

    def _execute_stored_comment_tool(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        if fn_name not in STORED_COMMENT_TOOL_NAMES:
            return None
        if self.db_session is None:
            return {"error": "数据库未连接，无法操作已入库评论", "source": "database"}

        from app.platforms.types import normalize_platform

        platform = normalize_platform(str(fn_args.get("platform") or self.platform))
        service = StoredCommentService(self.db_session, self.settings, tenant_id=self.tenant_id)

        if fn_name == "query_stored_contents":
            return service.query_contents(
                platform=platform,
                offset=int(fn_args.get("offset") or 0),
                limit=int(fn_args.get("limit") or 20),
            )

        if fn_name == "query_stored_comments":
            content_id = str(fn_args.get("content_id") or "").strip() or None
            comment_text_contains = str(fn_args.get("comment_text_contains") or "").strip() or None
            return service.query_comments(
                platform=platform,
                content_id=content_id,
                comment_text_contains=comment_text_contains,
                offset=int(fn_args.get("offset") or 0),
                limit=int(fn_args.get("limit") or 20),
            )

        if fn_name == "get_stored_content_detail":
            content_id = str(fn_args.get("content_id") or "").strip()
            if not content_id:
                return {"error": "缺少 content_id", "source": "database", "status": "failed"}
            detail = service.get_content_detail(
                platform=platform,
                content_id=content_id,
                max_comments=int(fn_args.get("max_comments") or 50),
            )
            if detail is None:
                return {
                    "source": "database",
                    "status": "not_found",
                    "error": "内容不存在",
                    "platform": platform,
                    "content_id": content_id,
                }
            return detail

        if fn_name == "get_stored_comment":
            comment_id = str(fn_args.get("comment_id") or "").strip()
            if not comment_id:
                return {"error": "缺少 comment_id", "source": "database", "status": "failed"}
            content_id = str(fn_args.get("content_id") or "").strip() or None
            return service.get_comment(
                platform=platform,
                comment_id=comment_id,
                content_id=content_id,
            )

        if fn_name == "create_stored_comment":
            content_id = str(fn_args.get("content_id") or "").strip()
            comment_id = str(fn_args.get("comment_id") or "").strip()
            comment_text = str(fn_args.get("comment_text") or "").strip()
            if not content_id or not comment_id or not comment_text:
                return {
                    "error": "缺少 content_id / comment_id / comment_text",
                    "source": "database",
                    "status": "failed",
                }
            raw_data = fn_args.get("raw_data")
            if raw_data is not None and not isinstance(raw_data, dict):
                return {"error": "raw_data 必须是对象", "source": "database", "status": "failed"}
            return service.create_comment(
                platform=platform,
                content_id=content_id,
                comment_id=comment_id,
                comment_text=comment_text,
                nickname=str(fn_args.get("nickname") or ""),
                content_url=str(fn_args.get("content_url") or "").strip() or None,
                parent_comment_id=str(fn_args.get("parent_comment_id") or "").strip() or None,
                digg_count=int(fn_args.get("digg_count") or 0),
                create_time=int(fn_args["create_time"]) if fn_args.get("create_time") is not None else None,
                raw_data=raw_data,
            )

        if fn_name == "update_stored_comment":
            content_id = str(fn_args.get("content_id") or "").strip()
            comment_id = str(fn_args.get("comment_id") or "").strip()
            if not content_id or not comment_id:
                return {
                    "error": "缺少 content_id / comment_id",
                    "source": "database",
                    "status": "failed",
                }
            raw_data = fn_args.get("raw_data")
            if raw_data is not None and not isinstance(raw_data, dict):
                return {"error": "raw_data 必须是对象", "source": "database", "status": "failed"}
            return service.update_comment(
                platform=platform,
                content_id=content_id,
                comment_id=comment_id,
                nickname=str(fn_args["nickname"]) if fn_args.get("nickname") is not None else None,
                comment_text=str(fn_args["comment_text"]) if fn_args.get("comment_text") is not None else None,
                digg_count=int(fn_args["digg_count"]) if fn_args.get("digg_count") is not None else None,
                parent_comment_id=(
                    str(fn_args["parent_comment_id"]) if fn_args.get("parent_comment_id") is not None else None
                ),
                content_url=str(fn_args["content_url"]) if fn_args.get("content_url") is not None else None,
                raw_data=raw_data,
                create_time=int(fn_args["create_time"]) if fn_args.get("create_time") is not None else None,
            )

        if fn_name == "delete_stored_comment":
            content_id = str(fn_args.get("content_id") or "").strip()
            comment_id = str(fn_args.get("comment_id") or "").strip()
            if not content_id or not comment_id:
                return {
                    "error": "缺少 content_id / comment_id",
                    "source": "database",
                    "status": "failed",
                }
            return service.delete_comment(
                platform=platform,
                content_id=content_id,
                comment_id=comment_id,
            )

        if fn_name == "delete_stored_content":
            content_id = str(fn_args.get("content_id") or "").strip()
            if not content_id:
                return {"error": "缺少 content_id", "source": "database", "status": "failed"}
            return service.delete_content(platform=platform, content_id=content_id)

        return None

    async def _execute_skillhub_tool(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
        *,
        skills_by_id: dict[str, Any],
    ) -> dict[str, Any] | None:
        if fn_name == "skillhub_search":
            query = str(fn_args.get("query") or "").strip()
            if not query:
                return {"error": "缺少 query"}
            limit = int(fn_args.get("limit") or 10)
            installer = SkillHubInstaller(self.settings, self.tenant_id)
            try:
                data = await installer.search(query, limit=min(limit, 50))
            except Exception as exc:
                return {"error": str(exc)}
            items = data.get("items") or []
            return {
                "items": [
                    {
                        "namespace": i.get("namespace"),
                        "slug": i.get("slug"),
                        "version": i.get("latestVersion") or i.get("latest_version"),
                        "summary": i.get("summary"),
                        "coordinate": (
                            i.get("slug")
                            if (i.get("namespace") or "global") == "global"
                            else f"@{i.get('namespace')}/{i.get('slug')}"
                        ),
                    }
                    for i in items
                ],
                "total": data.get("total", len(items)),
            }

        if fn_name == "skillhub_install":
            installer = SkillHubInstaller(self.settings, self.tenant_id)
            try:
                result = await installer.install(
                    coordinate=fn_args.get("coordinate"),
                    namespace=fn_args.get("namespace"),
                    slug=fn_args.get("slug"),
                    version=fn_args.get("version"),
                    overwrite=bool(fn_args.get("overwrite")),
                )
                return result
            except Exception as exc:
                return {"error": str(exc)}

        if fn_name == "read_skill_resource":
            skill_id = str(fn_args.get("skill_id") or "").strip()
            rel_path = str(fn_args.get("path") or "").strip()
            skill = skills_by_id.get(skill_id)
            if skill is None:
                return {"error": f"技能不存在: {skill_id}"}
            package_path = getattr(skill, "package_path", None)
            if not package_path:
                return {"error": "该技能无本地技能包目录"}
            return read_package_file(Path(package_path), rel_path)

        if fn_name == "run_skill_script":
            skill_id = str(fn_args.get("skill_id") or "").strip()
            script = str(fn_args.get("script") or "").strip()
            skill = skills_by_id.get(skill_id)
            if skill is None:
                return {"error": f"技能不存在: {skill_id}"}
            package_path = getattr(skill, "package_path", None)
            if not package_path:
                return {"error": "该技能无 scripts 包目录"}
            args = fn_args.get("args") or []
            if not isinstance(args, list):
                args = []
            return await run_package_script(
                Path(package_path),
                script,
                args,
                timeout_seconds=self.settings.skillhub_script_timeout_seconds,
            )

        return None

    def _build_all_tools_for_run(
        self,
        *,
        profile: AgentProfileOut,
        skills: list[Any],
        explicit_ids: set[str],
        mode: AgentMode,
    ) -> list[dict[str, Any]]:
        skill_tools = build_skill_tool_definitions(skills, explicit_skill_ids=explicit_ids)
        has_packages = any(getattr(s, "package_path", None) for s in skills)
        hub_tools = build_skillhub_tool_definitions(has_packages=has_packages or True)
        return self._append_tools_for_mode(
            filter_tools_for_mode(
                TOOL_DEFINITIONS
                + COMMENT_DATA_TOOL_DEFINITIONS
                + STORED_COMMENT_TOOL_DEFINITIONS
                + skill_tools
                + hub_tools,
                mode,
            ),
            mode,
        )

    async def _resolve_session(
        self,
        session_id: str | None,
        headless: bool | None,
        *,
        reuse_stable: bool = False,
    ) -> tuple[AgentBrowserSession, bool]:
        if session_id:
            session = self.session_manager.get(session_id)
            if session is None:
                session = await self.create_session(headless=headless, auto_start=False)
                return session, True
            if not session.is_started:
                return session, False
            if (
                session.tenant_id != self.tenant_id
                or session.account_id != self.account_id
                or session.platform != self.platform
            ):
                raise ValueError(
                    "浏览器会话与当前租户/账号/平台不匹配，请不传 session_id 以创建新会话"
                )
            return session, False
        if reuse_stable:
            session = await self.session_manager.create_stable(
                self.tenant_id,
                self.platform,
                self.settings,
                account_id=self.account_id,
                headless=headless,
            )
            return session, False
        session = await self.create_session(headless=headless, auto_start=False)
        return session, True

    async def _compress_and_sync(
        self,
        messages: list[dict[str, Any]],
        history: list[dict[str, Any]],
        client: AsyncOpenAI,
        model: str,
    ) -> AsyncIterator[AgentEvent]:
        compressed, event = await maybe_compress_history(
            history,
            client=client,
            model=model,
            settings=self.settings,
        )
        if event is None:
            return
        history.clear()
        history.extend(compressed)
        system_msg = messages[0] if messages else None
        messages.clear()
        if system_msg is not None:
            messages.append(system_msg)
        messages.extend(history)
        yield event

    async def _agent_loop(
        self,
        *,
        run: AgentRunRecord,
        session: AgentBrowserSession,
        messages: list[dict[str, Any]],
        history: list[dict[str, Any]],
        client: AsyncOpenAI,
        model: str,
        vision_model: str | None,
        all_tools: list[dict[str, Any]],
        skills_by_tool: dict[str, Any],
        skills_by_id: dict[str, Any],
        pw_executor: PlaywrightToolExecutor,
        skill_executor: SkillExecutor,
        mode: AgentMode,
        run_mode: RunMode,
        start_step: int = 1,
        provider: str = "deepseek",
        explicit_skill_ids: list[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        max_steps = self.settings.agent_max_steps
        terminal_status: str | None = None
        terminal_summary: str | None = None
        terminal_result: dict[str, Any] | None = None
        browser_session_id = session.session_id
        controller = self.run_controller
        recent_tool_calls: deque[str] = deque(maxlen=self._repeat_guard_window)
        tool_usage: dict[str, int] = {"read": 0, "write": 0, "skill": 0, "control": 0}
        failure_streak: dict[str, int] = {}
        skill_priority = [sid for sid in skills_by_id.keys()]
        phase = "plan"

        try:
            for step in range(start_step, max_steps + 1):
                if controller.is_cancelled(run.run_id):
                    terminal_status = "cancelled"
                    terminal_summary = "用户已停止执行"
                    yield AgentEvent(
                        type="cancelled",
                        data={"run_id": run.run_id, "summary": terminal_summary},
                    )
                    break

                yield AgentEvent(type="step", data={"step": step, "max_steps": max_steps})

                async for compress_event in self._compress_and_sync(
                    messages, history, client, model
                ):
                    yield compress_event

                active_model = vision_model if (vision_model and _has_image_content(messages)) else model
                repaired = repair_messages_tool_responses(messages)
                messages.clear()
                messages.extend(repaired)
                history.clear()
                history.extend(repaired)
                llm_messages = prepare_messages_for_provider(messages, provider)
                turn: AssistantTurn | None = None
                async for item in stream_chat_completion(
                    client,
                    model=active_model,
                    messages=llm_messages,
                    tools=all_tools,
                    stream=self.settings.agent_stream_enabled,
                ):
                    if controller.is_cancelled(run.run_id):
                        terminal_status = "cancelled"
                        terminal_summary = "用户已停止执行"
                        yield AgentEvent(
                            type="cancelled",
                            data={"run_id": run.run_id, "summary": terminal_summary},
                        )
                        break
                    if isinstance(item, AssistantTurn):
                        turn = item
                    else:
                        yield item

                if controller.is_cancelled(run.run_id):
                    if terminal_status != "cancelled":
                        terminal_status = "cancelled"
                        terminal_summary = "用户已停止执行"
                        yield AgentEvent(
                            type="cancelled",
                            data={"run_id": run.run_id, "summary": terminal_summary},
                        )
                    break

                if turn is None:
                    terminal_status = "failed"
                    terminal_summary = "LLM 无响应"
                    break

                assistant_entry = turn.to_message_entry()
                history.append(assistant_entry)
                messages.append(assistant_entry)

                tool_calls = turn.tool_calls
                if not tool_calls:
                    if turn.content:
                        terminal_status = "completed"
                        terminal_summary = turn.content
                    break

                for tool_call in tool_calls:
                    if controller.is_cancelled(run.run_id):
                        terminal_status = "cancelled"
                        terminal_summary = "用户已停止执行"
                        yield AgentEvent(
                            type="cancelled",
                            data={"run_id": run.run_id, "summary": terminal_summary},
                        )
                        break
                    phase = "act"
                    fn_name = tool_call["function"]["name"]
                    fn_args = parse_tool_arguments(tool_call["function"]["arguments"])
                    tool_call_id = tool_call["id"]
                    goal_text = self._primary_user_goal(history)
                    if self._skill_context_mismatch(goal_text, fn_name, fn_args):
                        mismatch_result = {
                            "status": "failed",
                            "error": (
                                "当前任务语境与抖音技能不匹配：该任务更像通用行情/分析问题，"
                                "不应优先走抖音搜索链路。请改用通用信息检索与分析策略。"
                            ),
                            "guard": "skill_context_mismatch",
                            "tool": fn_name,
                        }
                        yield AgentEvent(
                            type="tool_result",
                            data={
                                "tool": fn_name,
                                "tool_call_id": tool_call_id,
                                "result": mismatch_result,
                                "is_skill": fn_name.startswith("skill_") or fn_name in {"list_skills", "invoke_skill"},
                                "phase": "review",
                                "task_snapshot": self._extract_task_snapshot(history),
                                "agent_meta": self._agent_meta_payload(
                                    tool_usage=tool_usage,
                                    failure_streak=failure_streak,
                                    skill_priority=skill_priority,
                                ),
                            },
                        )
                        tool_entry = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "tool_name": fn_name,
                            "content": json.dumps(mismatch_result, ensure_ascii=False),
                        }
                        history.append(tool_entry)
                        messages.append(tool_entry)
                        phase = "review"
                        continue
                    current_snapshot = self._extract_task_snapshot(history)
                    if self._should_block_douyin_direct_search(
                        platform=self.platform,
                        fn_name=fn_name,
                        fn_args=fn_args,
                    ):
                        block_result = {
                            "status": "failed",
                            "error": (
                                "抖音禁止 Agent 用 browser 打开 /search/、/aisearch 或点搜索框。"
                                "关键词+评论请 invoke_skill douyin-keyword-comments / pipeline-keyword-video-comments。"
                            ),
                            "guard": "douyin_no_direct_search",
                            "tool": fn_name,
                        }
                        yield AgentEvent(
                            type="tool_result",
                            data={
                                "tool": fn_name,
                                "tool_call_id": tool_call_id,
                                "result": block_result,
                                "is_skill": fn_name.startswith("skill_") or fn_name in {"list_skills", "invoke_skill"},
                                "phase": "review",
                                "task_snapshot": current_snapshot,
                                "agent_meta": self._agent_meta_payload(
                                    tool_usage=tool_usage,
                                    failure_streak=failure_streak,
                                    skill_priority=skill_priority,
                                ),
                            },
                        )
                        tool_entry = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "tool_name": fn_name,
                            "content": json.dumps(block_result, ensure_ascii=False),
                        }
                        history.append(tool_entry)
                        messages.append(tool_entry)
                        phase = "review"
                        continue
                    if self._should_block_redundant_search(
                        fn_name=fn_name,
                        fn_args=fn_args,
                        snapshot=current_snapshot,
                    ):
                        block_result = {
                            "status": "failed",
                            "error": "已存在可复用的视频证据（aweme_id/video_url），禁止重复搜索；请直接进入单视频抓取链路。",
                            "guard": "evidence_first",
                            "tool": fn_name,
                            "task_snapshot_keys": sorted(list(current_snapshot.keys())),
                        }
                        yield AgentEvent(
                            type="tool_result",
                            data={
                                "tool": fn_name,
                                "tool_call_id": tool_call_id,
                                "result": block_result,
                                "is_skill": fn_name.startswith("skill_") or fn_name in {"list_skills", "invoke_skill"},
                                "phase": "review",
                                "task_snapshot": current_snapshot,
                                "agent_meta": self._agent_meta_payload(
                                    tool_usage=tool_usage,
                                    failure_streak=failure_streak,
                                    skill_priority=skill_priority,
                                ),
                            },
                        )
                        tool_entry = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "tool_name": fn_name,
                            "content": json.dumps(block_result, ensure_ascii=False),
                        }
                        history.append(tool_entry)
                        messages.append(tool_entry)
                        phase = "review"
                        continue
                    if self._should_block_manual_douyin_search_ui(
                        platform=self.platform,
                        fn_name=fn_name,
                        fn_args=fn_args,
                    ):
                        block_result = {
                            "status": "failed",
                            "error": (
                                "禁止用手动 browser 操作抖音搜索框。"
                                "请 invoke_skill douyin-keyword-comments 或 search-content（可加 show_browser=true）。"
                            ),
                            "guard": "douyin_no_manual_search_ui",
                            "tool": fn_name,
                        }
                        yield AgentEvent(
                            type="tool_result",
                            data={
                                "tool": fn_name,
                                "tool_call_id": tool_call_id,
                                "result": block_result,
                                "is_skill": False,
                                "phase": "review",
                                "task_snapshot": self._extract_task_snapshot(history),
                                "agent_meta": self._agent_meta_payload(
                                    tool_usage=tool_usage,
                                    failure_streak=failure_streak,
                                    skill_priority=skill_priority,
                                ),
                            },
                        )
                        tool_entry = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "tool_name": fn_name,
                            "content": json.dumps(block_result, ensure_ascii=False),
                        }
                        history.append(tool_entry)
                        messages.append(tool_entry)
                        phase = "review"
                        continue
                    is_skill = (
                        fn_name.startswith("skill_")
                        or fn_name in {"list_skills", "invoke_skill"}
                    )
                    category = self._tool_category(fn_name)
                    limit = self._tool_budget_limit(category)
                    if tool_usage.get(category, 0) >= limit:
                        budget_result = {
                            "status": "failed",
                            "error": (
                                f"{category} 类工具预算已用尽 ({limit})。"
                                "请复用当前证据并切换为其他策略，避免低效重复调用。"
                            ),
                            "guard": "tool_budget_exceeded",
                            "tool": fn_name,
                            "category": category,
                            "limit": limit,
                        }
                        yield AgentEvent(
                            type="tool_result",
                            data={
                                "tool": fn_name,
                                "tool_call_id": tool_call_id,
                                "result": budget_result,
                                "is_skill": is_skill,
                                "phase": phase,
                                "task_snapshot": self._extract_task_snapshot(history),
                                "agent_meta": self._agent_meta_payload(
                                    tool_usage=tool_usage,
                                    failure_streak=failure_streak,
                                    skill_priority=skill_priority,
                                ),
                            },
                        )
                        tool_entry = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "tool_name": fn_name,
                            "content": json.dumps(budget_result, ensure_ascii=False),
                        }
                        history.append(tool_entry)
                        messages.append(tool_entry)
                        continue
                    tool_usage[category] = tool_usage.get(category, 0) + 1
                    fingerprint = self._tool_call_fingerprint(fn_name, fn_args)
                    repeat_count = sum(1 for item in recent_tool_calls if item == fingerprint)
                    if repeat_count >= self._repeat_guard_threshold:
                        blocked_result = {
                            "status": "failed",
                            "error": (
                                "检测到重复调用同一工具且参数未变化。"
                                "请先复用已有历史与接口数据，再更换策略（例如改用 "
                                "browser_get_page_info / browser_get_network_data，或基于已拿到的 "
                                "aweme_id 直接抓取单视频评论），避免从头重复搜索。"
                            ),
                            "guard": "repeat_tool_call",
                            "tool": fn_name,
                            "repeat_count": repeat_count + 1,
                        }
                        yield AgentEvent(
                            type="tool_result",
                            data={
                                "tool": fn_name,
                                "tool_call_id": tool_call_id,
                                "result": blocked_result,
                                "is_skill": is_skill,
                                "phase": phase,
                                "task_snapshot": self._extract_task_snapshot(history),
                                "agent_meta": self._agent_meta_payload(
                                    tool_usage=tool_usage,
                                    failure_streak=failure_streak,
                                    skill_priority=skill_priority,
                                ),
                            },
                        )
                        tool_entry = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "tool_name": fn_name,
                            "content": json.dumps(blocked_result, ensure_ascii=False),
                        }
                        history.append(tool_entry)
                        messages.append(tool_entry)
                        continue
                    recent_tool_calls.append(fingerprint)

                    if fn_name == "submit_plan":
                        phase = "review"
                        plan = PendingPlan(
                            summary=str(fn_args.get("summary", "")),
                            steps=list(fn_args.get("steps") or []),
                        )
                        run.pending_plan = plan
                        run.loop_state = None
                        run.pending_approval = None
                        self._persist_run(run, history, "waiting_plan")
                        yield AgentEvent(
                            type="plan",
                            data={
                                "summary": plan.summary,
                                "steps": plan.steps,
                                "run_id": run.run_id,
                            },
                        )
                        yield AgentEvent(
                            type="done",
                            data={
                                "status": "waiting_plan",
                                "summary": plan.summary,
                                "session_id": browser_session_id,
                                "run_id": run.run_id,
                            },
                        )
                        return

                    if requires_approval(fn_name, run_mode=run_mode, mode=mode):
                        deferred = trim_assistant_tool_call(messages, history, tool_call_id)
                        run.pending_approval = PendingApproval(
                            tool_call_id=tool_call_id,
                            tool=fn_name,
                            arguments=fn_args,
                            step=step,
                        )
                        run.loop_state = LoopState(
                            messages=messages,
                            history=history,
                            step=step,
                            provider=run.provider,
                            agent_profile_id=run.agent_profile_id or profile.id,
                            explicit_skill_ids=[],
                            mode=mode,
                            run_mode=run_mode,
                            deferred_tool_calls=deferred,
                            phase=phase,
                            task_snapshot=self._extract_task_snapshot(history),
                        )
                        self._persist_run(run, history, "waiting_approval")
                        yield AgentEvent(
                            type="approval_request",
                            data={
                                "run_id": run.run_id,
                                "tool": fn_name,
                                "arguments": fn_args,
                                "tool_call_id": tool_call_id,
                                "step": step,
                            },
                        )
                        yield AgentEvent(
                            type="done",
                            data={
                                "status": "waiting_approval",
                                "summary": f"等待审批: {fn_name}",
                                "session_id": browser_session_id,
                                "run_id": run.run_id,
                            },
                        )
                        return

                    if fn_name == "spawn_task":
                        yield AgentEvent(
                            type="tool_start",
                            data={
                                "tool": fn_name,
                                "arguments": fn_args,
                                "tool_call_id": tool_call_id,
                                "is_skill": False,
                            },
                        )
                        checkpoint = await self._save_checkpoint_if_needed(
                            run_id=run.run_id,
                            step=step,
                            tool=fn_name,
                            session=session,
                        )
                        if checkpoint:
                            yield AgentEvent(
                                type="checkpoint",
                                data={
                                    "checkpoint_id": checkpoint.checkpoint_id,
                                    "step": checkpoint.step,
                                    "tool": checkpoint.tool,
                                    "url": checkpoint.url,
                                    "title": checkpoint.title,
                                },
                            )
                        sub_terminal: dict[str, Any] = {
                            "status": "failed",
                            "summary": "子任务未完成",
                        }
                        parent_profile = self.profile_store.resolve(
                            self.tenant_id,
                            run.agent_profile_id,
                        )
                        async for sub_event, sub_result in run_subagent(
                            task=str(fn_args.get("task", "")),
                            session=session,
                            client=client,
                            model=model,
                            settings_max_steps=self.settings.agent_subagent_max_steps,
                            max_steps=fn_args.get("max_steps"),
                            parent_run_id=run.run_id,
                            profile=parent_profile,
                        ):
                            if sub_result is not None:
                                sub_terminal = sub_result
                                continue
                            if sub_event.type == "done" and sub_event.data.get("subagent"):
                                continue
                            yield sub_event

                        result = {
                            "status": sub_terminal.get("status"),
                            "summary": sub_terminal.get("summary", ""),
                        }
                        yield AgentEvent(
                            type="tool_result",
                            data={
                                "tool": fn_name,
                                "tool_call_id": tool_call_id,
                                "result": result,
                                "is_skill": False,
                            },
                        )
                        tool_entry = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "tool_name": fn_name,
                            "content": json.dumps(compact_tool_result_for_llm(fn_name, result), ensure_ascii=False),
                        }
                        history.append(tool_entry)
                        messages.append(tool_entry)
                        if sub_terminal.get("status") == "failed":
                            phase = "review"
                            terminal_status = "failed"
                            terminal_summary = sub_terminal.get("summary", "")
                            break
                        continue

                    async for event in self._process_tool_call(
                        tool_call_id=tool_call_id,
                        fn_name=fn_name,
                        fn_args=fn_args,
                        is_skill=is_skill,
                        history=history,
                        messages=messages,
                        vision_model=vision_model,
                        pw_executor=pw_executor,
                        skill_executor=skill_executor,
                        skills_by_tool=skills_by_tool,
                        skills_by_id=skills_by_id,
                        mode=mode,
                        run_id=run.run_id,
                        step=step,
                        session=session,
                    ):
                        if event.type == "tool_result":
                            event.data["phase"] = phase
                            event.data["task_snapshot"] = self._extract_task_snapshot(history)
                            event.data["agent_meta"] = self._agent_meta_payload(
                                tool_usage=tool_usage,
                                failure_streak=failure_streak,
                                skill_priority=skill_priority,
                            )
                        yield event

                    if controller.is_cancelled(run.run_id):
                        terminal_status = "cancelled"
                        terminal_summary = "用户已停止执行"
                        yield AgentEvent(
                            type="cancelled",
                            data={"run_id": run.run_id, "summary": terminal_summary},
                        )
                        break

                    if fn_name == "task_complete":
                        phase = "review"
                        terminal_status = "completed"
                        terminal_summary = fn_args.get("summary", "")
                        raw_result = fn_args.get("result")
                        if isinstance(raw_result, dict):
                            terminal_result = raw_result
                        break
                    if fn_name == "task_failed":
                        phase = "review"
                        terminal_status = "failed"
                        terminal_summary = fn_args.get("reason", "")
                        break
                    last_tool = messages[-1] if messages else {}
                    if last_tool.get("role") == "tool":
                        try:
                            last_result = json.loads(last_tool.get("content") or "{}")
                        except json.JSONDecodeError:
                            last_result = {}
                        is_skill_call = fn_name.startswith("skill_") or fn_name == "invoke_skill"
                        if is_skill_call and (
                            last_result.get("error") or last_result.get("status") == "failed"
                        ):
                            recovery_entry = {
                                "role": "user",
                                "content": self._skill_failure_recovery_message(
                                    fn_name, fn_args, last_result
                                ),
                            }
                            history.append(recovery_entry)
                            messages.append(recovery_entry)
                            phase = "review"
                            failure_streak.clear()
                            continue
                        failure_type = self._classify_failure(last_result)
                        if failure_type:
                            phase = "review"
                            failure_streak[failure_type] = failure_streak.get(failure_type, 0) + 1
                            if failure_streak[failure_type] >= self._failure_help_threshold:
                                help_entry = {
                                    "role": "user",
                                    "content": (
                                        "【系统恢复建议】"
                                        + self._failure_guidance(failure_type)
                                    ),
                                }
                                history.append(help_entry)
                                messages.append(help_entry)
                                failure_streak[failure_type] = 0
                        else:
                            failure_streak.clear()
                            phase = "plan"

                if terminal_status:
                    break

                self._save_loop_checkpoint(
                    run,
                    history,
                    messages,
                    step=step + 1,
                    mode=mode,
                    run_mode=run_mode,
                    phase=phase,
                    explicit_skill_ids=explicit_skill_ids,
                )
            else:
                terminal_status = "failed"
                terminal_summary = f"已达到最大步数限制 ({max_steps})"

            run.pending_approval = None
            run.loop_state = None
            run.pending_plan = None
            final_status = terminal_status or "completed"
            final_snapshot = self._extract_task_snapshot(history)
            run.review_report = self._build_review_report(
                terminal_status=final_status,
                terminal_summary=terminal_summary or "",
                tool_usage=tool_usage,
                failure_streak=failure_streak,
                task_snapshot=final_snapshot,
            )
            run.validation_report = build_validation_report(
                status=final_status,
                summary=terminal_summary or "",
                task_snapshot=final_snapshot,
                review_report=run.review_report,
            )
            self._persist_run(run, history, final_status)
            await self._maybe_auto_dream(
                run.run_id,
                summary=terminal_summary or "",
                provider=provider,
            )
            done_data: dict[str, Any] = {
                "status": final_status,
                "summary": terminal_summary,
                "session_id": browser_session_id,
                "run_id": run.run_id,
                "history_count": len(run.messages),
                "phase": phase,
                "task_snapshot": final_snapshot,
                "review_report": run.review_report,
                "validation_report": run.validation_report,
            }
            if terminal_result is not None:
                done_data["result"] = terminal_result
            yield AgentEvent(type="done", data=done_data)
        except Exception as exc:
            self._persist_run(run, history, "failed")
            await self._maybe_auto_dream(run.run_id, summary=str(exc), provider=provider)
            yield AgentEvent(type="error", data={"message": str(exc)})
            yield AgentEvent(
                type="done",
                data={
                    "status": "failed",
                    "summary": str(exc),
                    "session_id": browser_session_id,
                    "run_id": run.run_id,
                },
            )

    @staticmethod
    async def _prepare_visible_browser_for_tool(
        session: AgentBrowserSession,
        fn_args: dict[str, Any],
        *,
        is_skill: bool,
    ) -> None:
        if not is_skill or not bool(fn_args.get("show_browser")):
            return
        if not headless_for_platform(session.settings, session.platform, session.headless):
            return
        session.headless = False
        if session.is_started:
            if getattr(session, "stable_mode", False):
                return
            await session.close()

    async def _process_tool_call(
        self,
        *,
        tool_call_id: str,
        fn_name: str,
        fn_args: dict[str, Any],
        is_skill: bool,
        history: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        vision_model: str | None,
        pw_executor: PlaywrightToolExecutor,
        skill_executor: SkillExecutor,
        skills_by_tool: dict[str, Any],
        skills_by_id: dict[str, Any],
        mode: AgentMode,
        run_id: str = "",
        step: int = 0,
        session: AgentBrowserSession | None = None,
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(
            type="tool_start",
            data={
                "tool": fn_name,
                "arguments": fn_args,
                "tool_call_id": tool_call_id,
                "is_skill": is_skill,
            },
        )

        if run_id and self._is_run_cancelled(run_id):
            yield AgentEvent(
                type="tool_result",
                data={
                    "tool": fn_name,
                    "tool_call_id": tool_call_id,
                    "result": self._cancelled_tool_result(),
                    "is_skill": is_skill,
                },
            )
            return

        if session is not None and tool_needs_browser(fn_name, is_skill=is_skill):
            await self._prepare_visible_browser_for_tool(session, fn_args, is_skill=is_skill)
            yield AgentEvent(
                type="status",
                data={"phase": "browser", "message": "正在启动浏览器…"},
            )
            try:
                page = await self._ensure_browser_with_cancel(session, run_id)
                if page is None:
                    yield AgentEvent(
                        type="tool_result",
                        data={
                            "tool": fn_name,
                            "tool_call_id": tool_call_id,
                            "result": self._cancelled_tool_result(),
                            "is_skill": is_skill,
                        },
                    )
                    return
            except TimeoutError:
                yield AgentEvent(
                    type="tool_result",
                    data={
                        "tool": fn_name,
                        "tool_call_id": tool_call_id,
                        "result": {"error": "浏览器启动超时，请稍后重试"},
                        "is_skill": is_skill,
                    },
                )
                return
            except Exception as exc:
                yield AgentEvent(
                    type="tool_result",
                    data={
                        "tool": fn_name,
                        "tool_call_id": tool_call_id,
                        "result": {"error": f"浏览器启动失败: {exc}"},
                        "is_skill": is_skill,
                    },
                )
                return

        if session is not None and run_id:
            checkpoint = await self._save_checkpoint_if_needed(
                run_id=run_id,
                step=step,
                tool=fn_name,
                session=session,
            )
            if checkpoint:
                yield AgentEvent(
                    type="checkpoint",
                    data={
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "step": checkpoint.step,
                        "tool": checkpoint.tool,
                        "url": checkpoint.url,
                        "title": checkpoint.title,
                    },
                )

        result: dict[str, Any] | None = None
        try:
            result = await self._execute_tool_with_cancel(
                run_id,
                lambda: self._execute_tool(
                    fn_name,
                    fn_args,
                    executor=pw_executor,
                    skill_executor=skill_executor,
                    skills_by_tool=skills_by_tool,
                    skills_by_id=skills_by_id,
                    mode=mode,
                ),
            )
        except Exception as exc:
            result = {"error": str(exc)}
        if result is None:
            result = {"error": "工具未返回结果"}

        screenshot_b64: str | None = None
        if fn_name == "browser_screenshot" and "base64" in result:
            screenshot_b64 = result.pop("base64")

        yield AgentEvent(
            type="tool_result",
            data={
                "tool": fn_name,
                "tool_call_id": tool_call_id,
                "result": result,
                "is_skill": is_skill,
            },
        )

        if screenshot_b64:
            yield AgentEvent(
                type="screenshot",
                data={"tool_call_id": tool_call_id, "base64": screenshot_b64},
            )

        tool_entry = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "tool_name": fn_name,
            "content": json.dumps(compact_tool_result_for_llm(fn_name, result), ensure_ascii=False),
        }
        history.append(tool_entry)
        messages.append(tool_entry)

        if screenshot_b64 and vision_model:
            vision_entry = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "这是 browser_screenshot 返回的当前页面截图，请结合视觉信息继续任务。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_b64}",
                            "detail": "auto",
                        },
                    },
                ],
            }
            history.append(vision_entry)
            messages.append(vision_entry)
        elif screenshot_b64:
            text_entry = {
                "role": "user",
                "content": (
                    "browser_screenshot 已完成，截图已在用户界面展示。"
                    "当前模型不支持视觉理解，请调用 browser_get_text 或 browser_get_page_info "
                    "获取页面文字与 URL 后继续。"
                ),
            }
            history.append(text_entry)
            messages.append(text_entry)

        if result.get("type") == "instruction" and result.get("instructions"):
            instruction_entry = {
                "role": "user",
                "content": (
                    f"【技能 {result.get('skill_name')} 完整指南】\n{result['instructions']}"
                ),
            }
            history.append(instruction_entry)
            messages.append(instruction_entry)

        if result.get("error"):
            yield AgentEvent(type="error", data={"message": result["error"]})

    async def run_chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        provider: Literal["openai", "deepseek"] | None = None,
        headless: bool | None = None,
        explicit_skill_ids: list[str] | None = None,
        agent_profile_id: str | None = None,
        mode: AgentMode = "agent",
        run_mode: RunMode = "auto",
        ui_flow_bootstrap: dict[str, Any] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        effective_provider: Literal["openai", "deepseek"] = provider or resolve_default_provider(self.settings)  # type: ignore[assignment]
        client, model = self._resolve_client(effective_provider)
        if client is None or model is None:
            yield AgentEvent(type="error", data={"message": f"未配置 {effective_provider} API Key"})
            return

        binding_error = self.binding_required_error()
        if binding_error:
            yield AgentEvent(type="error", data=binding_error)
            yield AgentEvent(
                type="done",
                data={"status": "failed", "summary": binding_error["message"]},
            )
            return

        explicit_ids = set(explicit_skill_ids or []) | set(parse_explicit_skill_ids(message))
        from app.services.dedicated_agent.service import DedicatedAgentService

        chat_profile_id = DedicatedAgentService.resolve_chat_profile_id(agent_profile_id)
        try:
            profile = self.profile_store.resolve(self.tenant_id, chat_profile_id)
        except ValueError as exc:
            yield AgentEvent(type="error", data={"message": str(exc)})
            return
        if profile.platforms and self.platform not in profile.platforms:
            yield AgentEvent(
                type="error",
                data={
                    "message": (
                        f"Agent「{profile.name}」不适用当前平台 {self.platform}，"
                        f"适用平台：{', '.join(profile.platforms)}"
                    ),
                },
            )
            return

        yield AgentEvent(type="status", data={"phase": "init", "message": "正在准备对话…"})
        try:
            session, created_new = await self._resolve_session(
                session_id,
                headless,
                reuse_stable=False,
            )
        except ValueError as exc:
            yield AgentEvent(type="error", data={"message": str(exc)})
            return

        bind_session_sandbox(
            session,
            agent_profile_id=profile.id,
            profile_skill_ids=profile.skill_ids,
            explicit_skill_ids=explicit_ids,
        )

        browser_session_id = session.session_id
        effective_run_id = run_id or session_id or browser_session_id
        run = self.run_store.get(self.tenant_id, effective_run_id)
        if run is None:
            run = self.run_store.create(
                run_id=effective_run_id,
                browser_session_id=browser_session_id,
                tenant_id=self.tenant_id,
                platform=self.platform,
                provider=effective_provider,
            )
        else:
            run.browser_session_id = browser_session_id
        run.mode = mode
        run.run_mode = run_mode
        run.provider = effective_provider
        run.agent_profile_id = profile.id
        if ui_flow_bootstrap:
            run.ui_flow_bootstrap = ui_flow_bootstrap
            self.run_store.save(run)

        await self.run_controller.register(effective_run_id)
        try:
            install_events = await auto_install_from_message(self.settings, self.tenant_id, message)
            for item in install_events:
                if item.get("installed"):
                    yield AgentEvent(
                        type="skill_installed",
                        data={
                            "slug": item.get("slug"),
                            "namespace": item.get("namespace"),
                            "version": item.get("version"),
                            "message": item.get("message"),
                        },
                    )
                elif item.get("error"):
                    yield AgentEvent(
                        type="skill_install_failed",
                        data={"coordinate": item.get("coordinate"), "error": item["error"]},
                    )

            skills = self._prioritize_skills(self.skill_store.list_enabled(self.tenant_id))
            skills = self._filter_skills_for_profile(skills, profile)
            skills_by_tool = {s.tool_name: s for s in skills}
            skills_by_id = {s.id: s for s in skills}
            all_tools = self._build_all_tools_for_run(
                profile=profile,
                skills=skills,
                explicit_ids=explicit_ids,
                mode=mode,
            )
            self._active_comment_file_refs = collect_comment_files_from_history(
                list(run.messages),
                self.settings,
            )
            vision_model = self._resolve_vision_model(effective_provider, model)
            provider_info = self.get_config()["providers"].get(effective_provider, {})

            yield AgentEvent(
                type="session",
                data={
                    "session_id": browser_session_id,
                    "run_id": effective_run_id,
                    "platform": session.platform,
                    "tenant_id": session.tenant_id,
                    "account_id": session.account_id,
                    "binding_status": self.platform_binding_status(),
                    "browser_ready": session.is_started,
                    "local_comment_files": self._active_comment_file_refs,
                    "created": created_new,
                    "skills_count": len(skills),
                    "history_count": len(run.messages),
                    "vision_enabled": vision_model is not None,
                    "stream_enabled": self.settings.agent_stream_enabled,
                    "compress_enabled": self.settings.agent_compress_enabled,
                    "provider": effective_provider,
                    "model": model,
                    "provider_note": provider_info.get("note"),
                    "mode": mode,
                    "run_mode": run_mode,
                    "agent_profile_id": profile.id,
                    "agent_profile_name": profile.name,
                    "phase": "plan",
                    "task_snapshot": {},
                    "agent_meta": self._agent_meta_payload(
                        tool_usage={"read": 0, "write": 0, "skill": 0, "control": 0},
                        failure_streak={},
                        skill_priority=[s.id for s in skills],
                    ),
                },
            )

            history = list(run.messages)
            history.append({"role": "user", "content": message})

            compressed, compress_event = await maybe_compress_history(
                history,
                client=client,
                model=model,
                settings=self.settings,
            )
            if compress_event is not None:
                history = compressed
                yield compress_event

            system_content = self._system_prompt_for_profile(
                profile,
                skills,
                explicit_ids,
                mode,
                user_query=message,
            )
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_content},
                *history,
            ]

            pw_executor = PlaywrightToolExecutor(session, self.settings)
            skill_executor = SkillExecutor(
                self.settings,
                self.tenant_id,
                self.platform,
                session,
                pw_executor,
                db_session=self.db_session,
            )

            self._save_loop_checkpoint(
                run,
                history,
                messages,
                step=1,
                mode=mode,
                run_mode=run_mode,
                phase="plan",
                explicit_skill_ids=list(explicit_ids),
            )

            yield AgentEvent(type="status", data={"phase": "think", "message": "正在思考…"})

            async for event in self._agent_loop(
                run=run,
                session=session,
                messages=messages,
                history=history,
                client=client,
                model=model,
                vision_model=vision_model,
                all_tools=all_tools,
                skills_by_tool=skills_by_tool,
                skills_by_id=skills_by_id,
                pw_executor=pw_executor,
                skill_executor=skill_executor,
                mode=mode,
                run_mode=run_mode,
                provider=effective_provider,
                explicit_skill_ids=list(explicit_ids),
            ):
                yield event
        except asyncio.CancelledError:
            self._mark_run_interrupted(effective_run_id)
            raise
        finally:
            self._active_comment_file_refs = []
            await self.run_controller.clear(effective_run_id)

    async def resume_run(self, run_id: str) -> AsyncIterator[AgentEvent]:
        run = self.run_store.get(self.tenant_id, run_id)
        if run is None:
            yield AgentEvent(type="error", data={"message": "对话 Run 不存在"})
            return
        if run.loop_state is None:
            yield AgentEvent(type="error", data={"message": "没有可恢复的执行进度"})
            return
        if run.status not in {"active", "interrupted"}:
            yield AgentEvent(
                type="error",
                data={"message": f"当前状态不可恢复: {run.status}"},
            )
            return

        state = run.loop_state
        session = self.session_manager.get(run.browser_session_id)
        if session is None:
            yield AgentEvent(type="error", data={"message": "浏览器会话已失效，请新建会话"})
            return

        client, model = self._resolve_client(state.provider)
        if client is None or model is None:
            yield AgentEvent(type="error", data={"message": "LLM 未配置"})
            return

        mode: AgentMode = state.mode  # type: ignore[assignment]
        run_mode: RunMode = state.run_mode  # type: ignore[assignment]
        messages = list(state.messages)
        history = list(state.history)
        start_step = max(1, state.step)

        profile = self.profile_store.resolve(self.tenant_id, run.agent_profile_id)
        skills = self._prioritize_skills(self.skill_store.list_enabled(self.tenant_id))
        skills = self._filter_skills_for_profile(skills, profile)
        explicit_ids = set(state.explicit_skill_ids or [])
        skills_by_tool = {s.tool_name: s for s in skills}
        skills_by_id = {s.id: s for s in skills}
        all_tools = self._build_all_tools_for_run(
            profile=profile,
            skills=skills,
            explicit_ids=explicit_ids,
            mode=mode,
        )
        vision_model = self._resolve_vision_model(state.provider, model)
        provider_info = self.get_config()["providers"].get(state.provider, {})

        resume_query = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    resume_query = content.strip()
                    break
        system_content = self._system_prompt_for_profile(
            profile,
            skills,
            explicit_ids,
            mode,
            user_query=resume_query,
        )
        _apply_system_prompt_to_messages(messages, system_content)

        run.status = "active"
        run.mode = mode
        run.run_mode = run_mode
        run.provider = state.provider
        self.run_store.save(run)

        yield AgentEvent(
            type="session",
            data={
                "session_id": run.browser_session_id,
                "run_id": run_id,
                "platform": session.platform,
                "tenant_id": session.tenant_id,
                "created": False,
                "resumed": True,
                "skills_count": len(skills),
                "history_count": len(run.messages),
                "vision_enabled": vision_model is not None,
                "stream_enabled": self.settings.agent_stream_enabled,
                "compress_enabled": self.settings.agent_compress_enabled,
                "provider": state.provider,
                "model": model,
                "provider_note": provider_info.get("note"),
                "mode": mode,
                "run_mode": run_mode,
                "agent_profile_id": profile.id,
                "agent_profile_name": profile.name,
                "phase": state.phase,
                "task_snapshot": state.task_snapshot,
                "agent_meta": self._agent_meta_payload(
                    tool_usage={"read": 0, "write": 0, "skill": 0, "control": 0},
                    failure_streak={},
                    skill_priority=[s.id for s in skills],
                ),
            },
        )

        bind_session_sandbox(
            session,
            agent_profile_id=profile.id,
            profile_skill_ids=profile.skill_ids,
            explicit_skill_ids=explicit_ids,
        )

        pw_executor = PlaywrightToolExecutor(session, self.settings)
        skill_executor = SkillExecutor(
            self.settings,
            self.tenant_id,
            self.platform,
            session,
            pw_executor,
            db_session=self.db_session,
        )

        await self.run_controller.register(run_id)
        try:
            async for event in self._agent_loop(
                run=run,
                session=session,
                messages=messages,
                history=history,
                client=client,
                model=model,
                vision_model=vision_model,
                all_tools=all_tools,
                skills_by_tool=skills_by_tool,
                skills_by_id=skills_by_id,
                pw_executor=pw_executor,
                skill_executor=skill_executor,
                mode=mode,
                run_mode=run_mode,
                start_step=start_step,
                provider=state.provider,
                explicit_skill_ids=list(explicit_ids),
            ):
                yield event
        except asyncio.CancelledError:
            self._mark_run_interrupted(run_id)
            raise
        finally:
            await self.run_controller.clear(run_id)

    async def resume_approval(
        self,
        run_id: str,
        *,
        approved: bool,
    ) -> AsyncIterator[AgentEvent]:
        run = self.run_store.get(self.tenant_id, run_id)
        if run is None or run.pending_approval is None or run.loop_state is None:
            yield AgentEvent(type="error", data={"message": "无待审批操作"})
            return

        state = run.loop_state
        pending = run.pending_approval
        session = self.session_manager.get(run.browser_session_id)
        if session is None:
            yield AgentEvent(type="error", data={"message": "浏览器会话已失效"})
            return

        client, model = self._resolve_client(state.provider)
        if client is None or model is None:
            yield AgentEvent(type="error", data={"message": "LLM 未配置"})
            return

        messages = list(state.messages)
        history = list(state.history)
        mode: AgentMode = state.mode  # type: ignore[assignment]
        run_mode: RunMode = state.run_mode  # type: ignore[assignment]

        profile = self.profile_store.resolve(self.tenant_id, run.agent_profile_id)
        skills = self._prioritize_skills(self.skill_store.list_enabled(self.tenant_id))
        skills = self._filter_skills_for_profile(skills, profile)
        explicit_ids = set(state.explicit_skill_ids or [])
        skills_by_tool = {s.tool_name: s for s in skills}
        skills_by_id = {s.id: s for s in skills}
        all_tools = self._build_all_tools_for_run(
            profile=profile,
            skills=skills,
            explicit_ids=explicit_ids,
            mode=mode,
        )
        vision_model = self._resolve_vision_model(state.provider, model)

        approval_query = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    approval_query = content.strip()
                    break
        system_content = self._system_prompt_for_profile(
            profile,
            skills,
            explicit_ids,
            mode,
            user_query=approval_query,
        )
        _apply_system_prompt_to_messages(messages, system_content)

        pw_executor = PlaywrightToolExecutor(session, self.settings)
        skill_executor = SkillExecutor(
            self.settings,
            self.tenant_id,
            self.platform,
            session,
            pw_executor,
            db_session=self.db_session,
        )

        run.pending_approval = None
        run.loop_state = None

        if not approved:
            tool_entry = {
                "role": "tool",
                "tool_call_id": pending.tool_call_id,
                "tool_name": pending.tool,
                "content": json.dumps({"rejected": True, "message": "用户拒绝执行此操作"}, ensure_ascii=False),
            }
            history.append(tool_entry)
            messages.append(tool_entry)
        elif pending.tool == "spawn_task":
            yield AgentEvent(
                type="tool_start",
                data={
                    "tool": pending.tool,
                    "arguments": pending.arguments,
                    "tool_call_id": pending.tool_call_id,
                    "is_skill": False,
                },
            )
            checkpoint = await self._save_checkpoint_if_needed(
                run_id=run.run_id,
                step=pending.step,
                tool=pending.tool,
                session=session,
            )
            if checkpoint:
                yield AgentEvent(
                    type="checkpoint",
                    data={
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "step": checkpoint.step,
                        "tool": checkpoint.tool,
                        "url": checkpoint.url,
                        "title": checkpoint.title,
                    },
                )
            sub_terminal: dict[str, Any] = {"status": "failed", "summary": "子任务未完成"}
            approval_profile = self.profile_store.resolve(self.tenant_id, run.agent_profile_id)
            async for sub_event, sub_result in run_subagent(
                task=str(pending.arguments.get("task", "")),
                session=session,
                client=client,
                model=model,
                settings_max_steps=self.settings.agent_subagent_max_steps,
                max_steps=pending.arguments.get("max_steps"),
                parent_run_id=run.run_id,
                profile=approval_profile,
            ):
                if sub_result is not None:
                    sub_terminal = sub_result
                    continue
                if sub_event.type == "done" and sub_event.data.get("subagent"):
                    continue
                yield sub_event
            result = {
                "status": sub_terminal.get("status"),
                "summary": sub_terminal.get("summary", ""),
            }
            yield AgentEvent(
                type="tool_result",
                data={
                    "tool": pending.tool,
                    "tool_call_id": pending.tool_call_id,
                    "result": result,
                    "is_skill": False,
                },
            )
            tool_entry = {
                "role": "tool",
                "tool_call_id": pending.tool_call_id,
                "tool_name": pending.tool,
                "content": json.dumps(compact_tool_result_for_llm(fn_name, result), ensure_ascii=False),
            }
            history.append(tool_entry)
            messages.append(tool_entry)
        else:
            async for event in self._process_tool_call(
                tool_call_id=pending.tool_call_id,
                fn_name=pending.tool,
                fn_args=pending.arguments,
                is_skill=pending.tool.startswith("skill_") or pending.tool == "invoke_skill",
                history=history,
                messages=messages,
                vision_model=vision_model,
                pw_executor=pw_executor,
                skill_executor=skill_executor,
                skills_by_tool=skills_by_tool,
                skills_by_id=skills_by_id,
                mode=mode,
                run_id=run.run_id,
                step=pending.step,
                session=session,
            ):
                if event.type != "error":
                    yield event

        deferred = list(state.deferred_tool_calls or [])
        for tc in deferred:
            fn_name = tc["function"]["name"]
            fn_args = parse_tool_arguments(tc["function"]["arguments"])
            tool_call_id = tc["id"]
            is_skill = (
                fn_name.startswith("skill_")
                or fn_name in {"list_skills", "invoke_skill"}
            )
            async for event in self._process_tool_call(
                tool_call_id=tool_call_id,
                fn_name=fn_name,
                fn_args=fn_args,
                is_skill=is_skill,
                history=history,
                messages=messages,
                vision_model=vision_model,
                pw_executor=pw_executor,
                skill_executor=skill_executor,
                skills_by_tool=skills_by_tool,
                skills_by_id=skills_by_id,
                mode=mode,
                run_id=run.run_id,
                step=pending.step,
                session=session,
            ):
                if event.type != "error":
                    yield event

        repaired = repair_messages_tool_responses(messages)
        messages.clear()
        messages.extend(repaired)
        history.clear()
        history.extend(repaired)

        await self.run_controller.register(run.run_id)
        try:
            async for event in self._agent_loop(
                run=run,
                session=session,
                messages=messages,
                history=history,
                client=client,
                model=model,
                vision_model=vision_model,
                all_tools=all_tools,
                skills_by_tool=skills_by_tool,
                skills_by_id=skills_by_id,
                pw_executor=pw_executor,
                skill_executor=skill_executor,
                mode=mode,
                run_mode=run_mode,
                start_step=pending.step,
                provider=state.provider,
            ):
                yield event
        finally:
            await self.run_controller.clear(run.run_id)

    async def resume_plan(
        self,
        run_id: str,
        *,
        approved: bool,
    ) -> AsyncIterator[AgentEvent]:
        run = self.run_store.get(self.tenant_id, run_id)
        if run is None or run.pending_plan is None:
            yield AgentEvent(type="error", data={"message": "无待确认计划"})
            return

        plan = run.pending_plan
        run.pending_plan = None

        if not approved:
            self._persist_run(run, run.messages, "completed")
            yield AgentEvent(
                type="done",
                data={"status": "cancelled", "summary": "用户拒绝了计划", "run_id": run_id},
            )
            return

        steps_text = "\n".join(
            f"{s.get('step', i+1)}. {s.get('action', '')}: {s.get('detail', '')}"
            for i, s in enumerate(plan.steps)
        )
        message = (
            f"用户已批准以下计划，请切换到 Agent 模式逐步执行：\n"
            f"摘要：{plan.summary}\n步骤：\n{steps_text}"
        )

        async for event in self.run_chat(
            message,
            session_id=run.browser_session_id,
            run_id=run_id,
            provider=run.provider,  # type: ignore[arg-type]
            agent_profile_id=run.agent_profile_id,
            mode="agent",
            run_mode=run.run_mode,  # type: ignore[arg-type]
        ):
            yield event
