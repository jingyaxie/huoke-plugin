from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.antibot import LoginRequiredError, headless_for_platform
from app.platforms.registry import get_dm_tool, get_follow_tool, get_session_store
from app.platforms.douyin.profile import build_profile_url as douyin_profile_url
from app.platforms.xiaohongshu.profile import build_profile_url as xhs_profile_url
from app.platforms.kuaishou.utils import build_profile_url as ks_profile_url
from app.schemas.skill import SkillOut
from app.services.comment_crawler_service import CommentCrawlerService
from app.services.supervisor_crawl_helpers import comment_capture_days_from, video_publish_days_from
from app.services.playwright_tools import PlaywrightToolExecutor
from app.services.agent_browser_session import AgentBrowserSession
from app.platforms.types import platform_from_content_url
from app.services.platform_skill_map import platform_for_skill_id

_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
DEFAULT_CRAWL_VIDEO_LIMIT = 5

_LOCAL_COMMENT_HINT = (
    "完整评论已写入 output_file；后续汇总/筛选意向请用 analyze_local_comments 或 read_local_comments，"
    "勿对同一视频重复 invoke content-comments。"
)


def _crawl_video_limit(params: dict[str, Any], *, default: int = DEFAULT_CRAWL_VIDEO_LIMIT) -> int:
    for key in ("crawl_video_limit", "video_limit", "content_limit", "limit", "video_limit_per_batch"):
        val = params.get(key)
        if val is None or val == "":
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return default


def _nickname_from_row(row: dict[str, Any]) -> str | None:
    for key in ("nickname", "user_name", "username"):
        if row.get(key):
            return str(row[key])[:40]
    user = row.get("user")
    if isinstance(user, dict) and user.get("nickname"):
        return str(user["nickname"])[:40]
    return None


def _slim_comment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    comments = payload.get("comments") or []
    preview = []
    for row in comments[:8]:
        if not isinstance(row, dict):
            continue
        text = str(row.get("comment") or row.get("text") or "")[:120]
        preview.append(
            {
                "nickname": _nickname_from_row(row),
                "comment": text,
                "digg_count": row.get("digg_count"),
            }
        )
    slim = {k: v for k, v in payload.items() if k != "comments"}
    slim["comments_count"] = len(comments)
    slim["comments_preview"] = preview
    return slim


def _slim_keyword_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slimmed: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        slimmed.append(
            {
                "aweme_id": item.get("aweme_id"),
                "video_url": item.get("video_url") or item.get("note_url"),
                "total_comments_captured": item.get("total_comments_captured"),
                "api_total_top_comments": item.get("api_total_top_comments"),
            }
        )
    return slimmed


def _coerce_param(value: Any, param_type: str) -> Any:
    if value is None:
        return None
    if param_type == "integer":
        return int(value)
    if param_type == "number":
        return float(value)
    if param_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}
    return str(value)


def _resolve_params(skill: SkillOut, raw_args: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for param in skill.parameters:
        if param.name in raw_args:
            resolved[param.name] = _coerce_param(raw_args[param.name], param.type)
        elif param.default is not None:
            resolved[param.name] = param.default
        elif param.required:
            raise ValueError(f"缺少必填参数: {param.name}")
    for key, value in raw_args.items():
        if key not in resolved:
            resolved[key] = value
    return resolved


def _interpolate(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in params:
                return match.group(0)
            return str(params[key])

        return _TEMPLATE_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, params) for item in value]
    return value


class SkillExecutor:
    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        platform: str,
        session: AgentBrowserSession,
        pw_executor: PlaywrightToolExecutor,
        db_session: Session | None = None,
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.session = session
        self.pw_executor = pw_executor
        self.db_session = db_session

    def _resolve_platform(self, skill: SkillOut, content_url: str | None = None) -> str:
        """平台专属 skill 按 skill_id 路由；通用 skill 优先从内容链接推断平台。"""
        mapped = platform_for_skill_id(skill.id)
        if mapped:
            return mapped
        url_platform = platform_from_content_url(content_url)
        if url_platform:
            return url_platform
        return self.platform

    def _comment_crawler_service(self, skill: SkillOut, content_url: str | None = None) -> CommentCrawlerService:
        return CommentCrawlerService(
            self.settings,
            tenant_id=self.tenant_id,
            platform=self._resolve_platform(skill, content_url),
            account_id=self.session.account_id,
            session=self.db_session,
        )

    def _interaction_log_service(self):
        from app.services.interaction_log_service import InteractionLogService

        return InteractionLogService(self.db_session, self.settings, tenant_id=self.tenant_id)

    def _record_interaction_log(
        self,
        params: dict[str, Any],
        *,
        action: str,
        ok: bool,
        platform: str | None = None,
        comment_id: str | None = None,
        content_id: str | None = None,
        content_url: str | None = None,
        target_user_id: str | None = None,
        target_sec_uid: str | None = None,
        target_nickname: str | None = None,
        reply_text: str | None = None,
        error_message: str | None = None,
        raw_result: dict[str, Any] | None = None,
    ) -> None:
        if self.db_session is None:
            return
        try:
            self._interaction_log_service().record(
                platform=platform or self.platform,
                action=action,
                status="ok" if ok else "failed",
                account_id=self.session.account_id,
                comment_id=comment_id,
                content_id=content_id,
                content_url=content_url,
                target_user_id=target_user_id,
                target_sec_uid=target_sec_uid,
                target_nickname=target_nickname,
                reply_text=reply_text,
                keyword=str(params.get("keyword") or "").strip() or None,
                agent_profile_id=str(params.get("agent_profile_id") or "").strip() or None,
                task_id=str(params.get("task_id") or params.get("job_id") or "").strip() or None,
                error_message=error_message,
                raw_result=raw_result,
            )
        except Exception:
            self.db_session.rollback()

    def _resolve_show_browser(self, params: dict[str, Any]) -> bool:
        """Agent 会话为可见模式时，Skill 默认走 有头浏览器。"""
        if "show_browser" in params:
            return bool(params.get("show_browser"))
        if self.session.is_started and not headless_for_platform(
            self.settings, self.platform, self.session.headless
        ):
            return True
        return False

    async def execute(self, skill: SkillOut, raw_args: dict[str, Any]) -> dict[str, Any]:
        try:
            params = _resolve_params(skill, raw_args)
            if skill.type == "instruction":
                return await self._execute_instruction(skill, params)
            if skill.type == "actions":
                return await self._execute_actions(skill, params)
            if skill.type == "builtin":
                return await self._execute_builtin(skill, params)
            return {"error": f"未知技能类型: {skill.type}"}
        except LoginRequiredError as exc:
            store = get_session_store(self.settings, self.platform)
            status = store.login_status(self.tenant_id, self.session.account_id)
            return {
                "error": str(exc),
                "code": "binding_required",
                "tenant_id": self.tenant_id,
                "account_id": self.session.account_id,
                "platform": self.platform,
                "binding_status": status.get("status", "missing"),
                "bind_api": (
                    f"/api/accounts/{self.session.account_id}/platforms/{self.platform}/server-login"
                ),
                "bindings_api": f"/api/accounts/{self.session.account_id}/bindings",
            }

    async def _execute_instruction(self, skill: SkillOut, params: dict[str, Any]) -> dict[str, Any]:
        instructions = _interpolate(skill.content, params)
        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "type": "instruction",
            "status": "activated",
            "instructions": instructions,
            "parameters": params,
            "message": f"技能「{skill.name}」已激活，请严格按 instructions 继续执行浏览器操作",
        }

    async def _execute_actions(self, skill: SkillOut, params: dict[str, Any]) -> dict[str, Any]:
        if not skill.actions:
            return {"error": "该技能未配置 actions 步骤"}
        step_results: list[dict[str, Any]] = []
        last_result: dict[str, Any] = {}
        for idx, action in enumerate(skill.actions, start=1):
            tool = action.tool
            args = _interpolate(dict(action.args), params)
            result, _ = await self.pw_executor.execute(tool, args)
            entry = {"step": idx, "tool": tool, "args": args, "result": result}
            step_results.append(entry)
            last_result = result
            if result.get("error"):
                return {
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "type": "actions",
                    "status": "failed",
                    "failed_step": idx,
                    "steps": step_results,
                    "error": result["error"],
                }
        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "type": "actions",
            "status": "completed",
            "steps": step_results,
            "result": last_result,
        }

    async def _execute_builtin(self, skill: SkillOut, params: dict[str, Any]) -> dict[str, Any]:
        handler = skill.builtin_handler
        if handler == "login_status":
            store = get_session_store(self.settings, self.platform)
            status = store.login_status(self.tenant_id, self.session.account_id)
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": status.get("status"),
                "message": status.get("message"),
            }
        if handler == "pipeline_keyword_comments":
            from app.services.skill_runner_service import SkillRunnerService

            runner = SkillRunnerService(
                self.settings,
                self.tenant_id,
                self.platform,
                account_id=self.session.account_id,
                db_session=self.db_session,
            )
            return await runner.execute_keyword_pipeline(
                keyword=str(params.get("keyword") or ""),
                video_limit=_crawl_video_limit(params),
                days=int(params.get("days") or 3),
                region=params.get("region"),
                headless=self.session.headless if params.get("show_browser") is not True else False,
                agent_fallback=bool(params.get("agent_fallback", True)),
                provider=str(params.get("provider") or "deepseek"),
                timeout_seconds=int(params.get("timeout_seconds") or 600),
                force_refresh=bool(params.get("force_refresh", False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
                guest_mode=bool(params.get("guest_mode", False)),
                session=self.session,
            )
        if handler == "follow_user":
            return await self._execute_follow(params, action="follow")
        if handler == "unfollow_user":
            return await self._execute_follow(params, action="unfollow")
        if handler == "send_dm":
            return await self._execute_send_dm(params)
        if handler == "reply_comment":
            return await self._execute_reply_comment(skill, params)
        if handler == "query_stored_comments":
            return self._execute_query_stored_comments(params)
        if handler == "query_interaction_stats":
            return self._execute_query_interaction_stats(params)
        if handler == "social_roam":
            return await self._execute_social_roam(params)
        if handler == "crawl_video_comments":
            video_url = params.get("video_url") or params.get("url") or params.get("note_url")
            if not video_url:
                return {"error": "缺少参数 video_url / note_url"}
            show_browser = self._resolve_show_browser(params)
            video_url_str = str(video_url)
            platform = self._resolve_platform(skill, video_url_str)
            existing_page = None
            if self.session is not None and platform == self.platform:
                try:
                    await self.session.ensure_started()
                    if self.session._is_alive():
                        existing_page = self.session.page
                except Exception as exc:
                    return {
                        "error": f"浏览器会话启动失败: {exc}",
                        "status": "failed",
                        "skill_id": skill.id,
                    }
            comment_days = comment_capture_days_from(None, params)
            capture_mode = str(params.get("capture_mode") or "").strip().lower()
            ui_passive = bool(params.get("ui_passive")) or capture_mode in {
                "video_url_ui_passive",
                "ui_passive",
            }
            job_id = str(params.get("job_id") or params.get("task_id") or "").strip()
            raw_params = {
                "job_id": job_id or None,
                "task_id": params.get("task_id"),
                "keyword": params.get("keyword"),
                "days": comment_days,
                "capture_mode": capture_mode or ("video_url_ui_passive" if ui_passive or show_browser else None),
            }
            service = self._comment_crawler_service(skill, video_url_str)
            payload, output, _cache = await service.crawl_video_comments(
                str(video_url),
                show_browser=show_browser,
                force_refresh=bool(params.get("force_refresh", False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
                days=comment_days,
                max_comments=int(params.get("max_comments") or 200),
                ui_passive=ui_passive,
                existing_page=existing_page,
                raw_params=raw_params,
            )
            captured = payload.get("total_comments_captured", 0)
            api_total = payload.get("api_total_top_comments")
            summary = f"已抓取 {captured} 条评论"
            if api_total is not None:
                summary += f"（接口总数 {api_total}）"
            status = "completed" if captured > 0 else "partial"
            if captured == 0 and payload.get("warning"):
                summary += f"；{payload['warning']}"
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": status,
                "platform": platform,
                "summary": summary,
                "video_url": payload.get("video_url") or payload.get("note_url") or video_url,
                "total_comments_captured": captured,
                "api_total_top_comments": api_total,
                "output_file": str(output),
                "result": _slim_comment_payload(payload),
                "hint": _LOCAL_COMMENT_HINT,
            }
        if handler == "crawl_keyword_comments":
            keyword = params.get("keyword")
            if not keyword:
                return {"error": "缺少参数 keyword"}
            show_browser = self._resolve_show_browser(params)
            guest_mode = bool(params.get("guest_mode", False))
            manual_search = bool(params.get("manual_search", False))
            include_full = bool(params.get("include_full_results", False))
            platform = self._resolve_platform(skill)
            existing_page = None
            if self.session is not None and platform == self.platform:
                try:
                    await self.session.ensure_started()
                    if self.session._is_alive():
                        existing_page = self.session.page
                except Exception as exc:
                    return {
                        "error": f"浏览器会话启动失败: {exc}",
                        "status": "failed",
                        "skill_id": skill.id,
                    }
            ui_search_only = bool(params.get("ui_search_only", False))
            if ui_search_only and existing_page is None:
                return {
                    "error": "UI 搜索需要任务浏览器会话，但页面未就绪或已关闭",
                    "status": "failed",
                    "skill_id": skill.id,
                    "diagnostic": "请点「继续执行」重试；若反复出现请检查 Chrome 是否被手动关闭",
                }
            service = self._comment_crawler_service(skill)
            search_days = video_publish_days_from(None, params)
            comment_days = comment_capture_days_from(None, params)
            ui_flow_context = None
            use_ui_crawl = bool(params.get("ui_first")) or str(params.get("capture_mode") or "").strip().lower() in {
                "ui_first",
                "ui_passive",
                "passive_api",
            }
            watched_ids = params.get("watched_content_ids") or []
            job_id = str(params.get("job_id") or params.get("task_id") or "").strip()
            supervisor_state = params.get("supervisor_state") if isinstance(params.get("supervisor_state"), dict) else {}
            if job_id:
                supervisor_state = {
                    "job_id": job_id,
                    "watched_content_ids": list(watched_ids),
                }
            if use_ui_crawl or ui_search_only or watched_ids:
                ui_flow_context = {
                    "watched_content_ids": watched_ids,
                    "supervisor_state": supervisor_state,
                    "task_id": job_id or params.get("task_id"),
                    "job_id": job_id or params.get("job_id"),
                    "db_session": self.db_session,
                    "ui_search_only": bool(params.get("ui_search_only", False)),
                    "inline_ui_outreach": bool(params.get("inline_ui_outreach", False)),
                    "capture_mode": params.get("capture_mode"),
                    "force_refresh": bool(params.get("force_refresh", True)),
                    "platform_options": params.get("platform_options"),
                }
            results, outputs, error, session_meta, _cache = await service.crawl_keyword_comments(
                keyword=str(keyword),
                limit=_crawl_video_limit(params),
                days=search_days,
                comment_days=comment_days,
                region=params.get("region"),
                show_browser=show_browser,
                guest_mode=guest_mode,
                force_refresh=bool(params.get("force_refresh", True if use_ui_crawl else False)),
                cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
                existing_page=existing_page,
                manual_search=manual_search,
                search_url_first=bool(params.get("search_url_first", False)),
                ui_search_only=bool(params.get("ui_search_only", False)),
                ui_first=use_ui_crawl,
                ui_flow_context=ui_flow_context,
                capture_mode=str(params.get("capture_mode") or "") or None,
            )
            meta = session_meta if isinstance(session_meta, dict) else {}
            videos_processed = int(meta.get("videos_processed") or len(results))
            raw_scanned = int(meta.get("raw_comments_scanned") or 0)
            search_fields = {
                k: meta[k]
                for k in (
                    "search_succeeded",
                    "search_url",
                    "discovered_video_urls",
                    "discovered_video_count",
                )
                if k in meta
            }
            if error and not results and videos_processed <= 0 and not search_fields.get("search_succeeded"):
                return {"error": error, "diagnostic": error, **search_fields}
            total_captured = sum(r.get("total_comments_captured", 0) for r in results)
            result_rows = results if include_full else _slim_keyword_results(results)
            if total_captured <= 0 and videos_processed <= 0:
                from app.services.supervisor_outreach import crawl_search_phase_succeeded

                if crawl_search_phase_succeeded(search_fields):
                    summary = f"关键词「{keyword}」搜索已成功，本批未抓到评论，将继续浏览更多视频"
                    partial: dict[str, Any] = {
                        "skill_id": skill.id,
                        "skill_name": skill.name,
                        "type": "builtin",
                        "handler": handler,
                        "status": "partial",
                        "platform": platform,
                        "summary": summary,
                        "keyword": keyword,
                        "videos_processed": videos_processed,
                        "total_comments_captured": 0,
                        "results": result_rows,
                        "diagnostic": error,
                        **search_fields,
                    }
                    if meta.get("crawl_search_exhausted"):
                        partial["crawl_search_exhausted"] = True
                    watched = meta.get("watched_content_ids")
                    job_id = str(params.get("job_id") or params.get("task_id") or "").strip()
                    watched_job_id = str(meta.get("watched_job_id") or job_id or "").strip()
                    if isinstance(watched, list) and watched:
                        partial["watched_content_ids"] = watched
                        if watched_job_id:
                            partial["watched_job_id"] = watched_job_id
                    return partial
                diag = str(error or "").strip()
                if not diag:
                    warnings = [
                        str(r.get("warning") or "").strip()
                        for r in results
                        if isinstance(r, dict) and r.get("warning")
                    ]
                    diag = "; ".join(w for w in warnings if w) or "未抓取到评论"
                return {
                    "error": diag,
                    "status": "failed",
                    "diagnostic": diag,
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "type": "builtin",
                    "handler": handler,
                    "platform": platform,
                    "summary": f"关键词「{keyword}」抓取失败：{diag}",
                    "keyword": keyword,
                    "videos_processed": videos_processed,
                    "total_comments_captured": 0,
                    "results": result_rows,
                    **search_fields,
                }
            summary = f"关键词「{keyword}」共处理 {videos_processed} 个视频，抓取 {total_captured} 条评论"
            if raw_scanned > total_captured:
                summary += f"（扫描 {raw_scanned} 条）"
            payload: dict[str, Any] = {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "platform": platform,
                "summary": summary,
                "keyword": keyword,
                "videos_processed": videos_processed,
                "total_comments_captured": total_captured,
                "raw_comments_scanned": raw_scanned,
                "guest_mode": meta.get("guest_mode", guest_mode),
                "session_mode": meta.get("session_mode", "logged_in"),
                "output_files": [str(p) for p in outputs],
                "results": result_rows,
                "diagnostic": error,
                "hint": _LOCAL_COMMENT_HINT,
                **search_fields,
            }
            if meta.get("comments_persisted"):
                payload["comments_persisted"] = int(meta.get("comments_persisted") or 0)
            job_id = str(params.get("job_id") or params.get("task_id") or "").strip()
            if not meta.get("cache_replay"):
                watched = meta.get("watched_content_ids")
                watched_job_id = str(meta.get("watched_job_id") or job_id or "").strip()
                if (
                    isinstance(watched, list)
                    and watched
                    and (not job_id or not watched_job_id or watched_job_id == job_id)
                ):
                    payload["watched_content_ids"] = watched
                    if watched_job_id:
                        payload["watched_job_id"] = watched_job_id
                if meta.get("crawl_search_exhausted"):
                    payload["crawl_search_exhausted"] = True
            if use_ui_crawl and meta.get("capture_mode"):
                payload["capture_mode"] = str(meta.get("capture_mode"))
            return payload
        if handler == "search_videos":
            keyword = params.get("keyword")
            if not keyword:
                return {"error": "缺少参数 keyword"}
            show_browser = self._resolve_show_browser(params)
            platform = self._resolve_platform(skill)
            source = str(params.get("source") or "auto").strip().lower()
            limit = int(params.get("limit", 20))
            hook_payload = None
            hook_output = None
            if platform == "douyin" and source in {"auto", "mobile_hook"} and not show_browser:
                from app.platforms.douyin.mobile_hook_search import (
                    search_videos_via_hook,
                    try_search_videos_via_hook,
                )

                if source == "mobile_hook":
                    try:
                        hook_payload, hook_output = await search_videos_via_hook(
                            self.settings,
                            keyword=str(keyword),
                            limit=limit,
                        )
                    except Exception as exc:
                        return {
                            "error": f"mobile_hook 搜索失败: {exc}",
                            "keyword": keyword,
                            "capture_method": "mobile_hook_bridge",
                            "source": "mobile_hook",
                        }
                else:
                    hook_result = await try_search_videos_via_hook(
                        self.settings,
                        keyword=str(keyword),
                        limit=limit,
                    )
                    if hook_result:
                        hook_payload, hook_output = hook_result
            if hook_payload is not None:
                payload = hook_payload
                output = hook_output
            else:
                existing_page = None
                if show_browser and self.session is not None:
                    try:
                        await self.session.ensure_started()
                        if platform == self.platform and self.session._is_alive():
                            existing_page = self.session.page
                    except Exception as exc:
                        return {
                            "error": f"浏览器会话启动失败: {exc}",
                            "status": "failed",
                            "skill_id": skill.id,
                        }
                service = self._comment_crawler_service(skill)
                try:
                    payload, output, _cache = await service.search_videos(
                        keyword=str(keyword),
                        limit=limit,
                        show_browser=show_browser,
                        days=params.get("days"),
                        region=params.get("region"),
                        force_refresh=bool(params.get("force_refresh", False)),
                        cache_ttl_hours=float(params.get("cache_ttl_hours") or 24),
                        ui_search_only=bool(params.get("ui_search_only")) or show_browser,
                        existing_page=existing_page,
                    )
                except NotImplementedError as exc:
                    return {"error": str(exc)}
            videos = payload.get("videos") or []
            if not videos:
                return {
                    "error": payload.get("diagnostic") or f"关键词「{keyword}」未搜索到视频",
                    "keyword": keyword,
                    "capture_method": payload.get("capture_method"),
                    "output_file": str(output) if output else None,
                }
            with_title = sum(1 for v in videos if v.get("title"))
            summary = f"关键词「{keyword}」搜索到 {payload.get('video_count', len(videos))} 个视频"
            if with_title:
                summary += f"（{with_title} 条含标题/作者/点赞）"
            if payload.get("diagnostic"):
                summary += f"；{payload['diagnostic']}"
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "platform": platform,
                "summary": summary,
                "keyword": keyword,
                "video_count": payload.get("video_count", len(videos)),
                "capture_method": payload.get("capture_method"),
                "output_file": str(output) if output else None,
                "videos_preview": videos[:10],
                "result": payload,
            }
        if handler == "collect_profile_videos":
            profile_url = params.get("profile_url") or params.get("input_url") or params.get("url")
            if not profile_url:
                return {"error": "缺少参数 profile_url"}
            show_browser = self._resolve_show_browser(params)
            platform = self._resolve_platform(skill)
            existing_page = None
            if show_browser and self.session is not None and platform == self.platform:
                try:
                    await self.session.ensure_started()
                    if self.session._is_alive():
                        existing_page = self.session.page
                except Exception as exc:
                    return {"error": f"浏览器会话启动失败: {exc}", "status": "failed", "skill_id": skill.id}
            service = self._comment_crawler_service(skill)
            search_days = video_publish_days_from(None, params)
            try:
                payload, output, _cache = await service.collect_profile_videos(
                    str(profile_url),
                    limit=_crawl_video_limit(params),
                    show_browser=show_browser,
                    days=search_days,
                    existing_page=existing_page,
                )
            except NotImplementedError as exc:
                return {"error": str(exc)}
            videos = payload.get("videos") or []
            if not videos:
                return {
                    "error": payload.get("diagnostic") or "主页未采集到视频",
                    "profile_url": profile_url,
                    "capture_method": payload.get("capture_method"),
                    "output_file": str(output) if output else None,
                }
            summary = f"主页采集到 {payload.get('video_count', len(videos))} 个视频"
            if payload.get("diagnostic"):
                summary += f"；{payload['diagnostic']}"
            return {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "platform": platform,
                "summary": summary,
                "profile_url": payload.get("profile_url") or profile_url,
                "video_count": payload.get("video_count", len(videos)),
                "capture_method": payload.get("capture_method"),
                "output_file": str(output) if output else None,
                "videos_preview": videos[:10],
                "result": payload,
            }
        if handler == "crawl_profile_comments":
            profile_url = params.get("profile_url") or params.get("input_url") or params.get("url")
            if not profile_url:
                return {"error": "缺少参数 profile_url"}
            show_browser = self._resolve_show_browser(params)
            platform = self._resolve_platform(skill)
            existing_page = None
            if self.session is not None and platform == self.platform:
                try:
                    await self.session.ensure_started()
                    if self.session._is_alive():
                        existing_page = self.session.page
                except Exception as exc:
                    return {
                        "error": f"浏览器会话启动失败: {exc}",
                        "status": "failed",
                        "skill_id": skill.id,
                    }
            service = self._comment_crawler_service(skill)
            search_days = video_publish_days_from(None, params)
            comment_days = comment_capture_days_from(None, params)
            include_full = bool(params.get("include_full_results", False))
            results, outputs, error, session_meta, _cache = await service.crawl_profile_comments(
                profile_url=str(profile_url),
                limit=_crawl_video_limit(params),
                days=search_days,
                comment_days=comment_days,
                show_browser=show_browser,
                max_comments=int(params.get("max_comments") or 200),
                existing_page=existing_page,
                video_publish_days=search_days,
            )
            meta = session_meta if isinstance(session_meta, dict) else {}
            videos_processed = int(meta.get("videos_processed") or len(results))
            if error and not results and videos_processed <= 0:
                return {"error": error, "diagnostic": error}
            total_captured = sum(r.get("total_comments_captured", 0) for r in results)
            result_rows = results if include_full else _slim_keyword_results(results)
            if total_captured <= 0 and videos_processed <= 0:
                diag = str(error or "").strip() or "主页视频未抓取到评论"
                return {
                    "error": diag,
                    "status": "failed",
                    "diagnostic": diag,
                    "skill_id": skill.id,
                    "profile_url": profile_url,
                    "videos_processed": videos_processed,
                    "results": result_rows,
                }
            api_total = sum(int(r.get("api_total_top_comments") or 0) for r in results)
            time_window = comment_days if comment_days is not None else search_days
            if total_captured <= 0 and videos_processed > 0 and api_total > 0 and time_window:
                filter_note = (
                    f"主页链接共处理 {videos_processed} 个视频，"
                    f"近 {time_window} 天内 0 条评论（接口共约 {api_total} 条，均被时间窗过滤）"
                )
            else:
                filter_note = ""
            summary = filter_note or f"主页链接共处理 {videos_processed} 个视频，抓取 {total_captured} 条评论"
            payload: dict[str, Any] = {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "type": "builtin",
                "handler": handler,
                "status": "completed",
                "platform": platform,
                "summary": summary,
                "profile_url": profile_url,
                "videos_processed": videos_processed,
                "total_comments_captured": total_captured,
                "output_files": [str(p) for p in outputs],
                "results": result_rows,
                "diagnostic": filter_note or error,
            }
            watched = meta.get("watched_content_ids")
            if isinstance(watched, list) and watched:
                payload["watched_content_ids"] = watched
            if meta.get("capture_mode"):
                payload["capture_mode"] = str(meta.get("capture_mode"))
            return payload
        return {"error": f"未实现的内置处理器: {handler}"}

    @staticmethod
    def _profile_url(platform: str, user_id: str, sec_uid: str | None = None) -> str:
        if platform == "douyin" and sec_uid:
            return douyin_profile_url(sec_uid)
        if platform == "xiaohongshu" and user_id:
            return xhs_profile_url(user_id)
        if platform == "kuaishou" and user_id:
            return ks_profile_url(user_id)
        return ""

    @staticmethod
    def _warm_outreach_requested(params: dict[str, Any]) -> bool:
        if params.get("warm_outreach"):
            return True
        if str(params.get("outreach_mode") or "").strip().lower() == "warm":
            return True
        return bool(params.get("ui_first")) and bool(params.get("comment_id"))

    async def _resolve_warm_outreach_comment_target(
        self, params: dict[str, Any]
    ) -> dict[str, Any] | dict[str, str]:
        """从参数或 DB 入库评论补全 comment_id / 文案 / sec_uid。"""
        comment_id = str(params.get("comment_id") or "").strip()
        comment_text = str(params.get("comment_text") or params.get("comment") or "").strip()
        sec_uid = str(params.get("sec_uid") or "").strip()
        user_id = str(params.get("user_id") or "").strip()
        nickname = str(params.get("username") or params.get("nickname") or "").strip()
        content_url = str(
            params.get("content_url")
            or params.get("video_url")
            or params.get("url")
            or ""
        ).strip()

        if self.db_session is not None and comment_id:
            from app.repositories.content_comment_repository import ContentCommentRepository
            from app.services.supervisor_outreach import _user_ids_from_comment_row

            record = ContentCommentRepository(self.db_session, self.tenant_id).find_comment_record(
                platform=self.platform,
                comment_id=comment_id,
            )
            if record:
                comment_text = comment_text or str(record.comment_text or "").strip()
                nickname = nickname or str(record.nickname or "").strip()
                content_url = content_url or str(record.content_url or "").strip()
                uid, suid = _user_ids_from_comment_row(
                    {
                        "user_id": user_id,
                        "sec_uid": sec_uid,
                        "raw_data": record.raw_data,
                    }
                )
                user_id = user_id or uid
                sec_uid = sec_uid or suid

        if not comment_id and not comment_text:
            return {
                "error": "warm_outreach 需要 comment_id 或 comment_text（来自抓取入库）",
                "status": "failed",
            }
        platform = (self.platform or "").strip().lower()
        if platform == "xiaohongshu":
            if not user_id:
                return {
                    "error": "warm_outreach 需要 user_id（来自抓取评论入库）",
                    "status": "failed",
                }
        elif not sec_uid:
            return {
                "error": "warm_outreach 需要 sec_uid（来自抓取评论入库 raw_data）",
                "status": "failed",
            }
        return {
            "comment_id": comment_id,
            "comment_text": comment_text,
            "sec_uid": sec_uid,
            "user_id": user_id,
            "nickname": nickname,
            "content_url": content_url,
        }

    async def _execute_warm_outreach_from_comment(self, params: dict[str, Any]) -> dict[str, Any]:
        target = await self._resolve_warm_outreach_comment_target(params)
        if target.get("status") == "failed":
            return target

        content_url = str(target.get("content_url") or "").strip()
        if not content_url:
            return {"error": "warm_outreach 需要 content_url / video_url", "status": "failed"}

        page = self.session.page if self.session.is_started else None
        if page is None:
            return {"error": "warm_outreach 需要有头浏览器 page", "status": "failed"}

        platform = (self.platform or "").strip().lower()
        dry_run = bool(params.get("dry_run", False))
        do_follow = bool(params.get("do_follow", True))

        if platform == "xiaohongshu":
            from app.services.social_roam.human.xiaohongshu.warm_outreach_profile import (
                warm_outreach_follow_from_comment,
            )

            result = await warm_outreach_follow_from_comment(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                account_id=self.session.account_id,
                content_url=content_url,
                comment_id=str(target.get("comment_id") or ""),
                comment_text=str(target.get("comment_text") or ""),
                user_id=str(target.get("user_id") or ""),
                nickname=str(target.get("nickname") or ""),
                do_follow=do_follow,
                dry_run=dry_run,
                scroll_rounds=int(params.get("scroll_rounds") or 8),
            )
            ok = bool(result.get("ok"))
            follow = result.get("follow") or {}
            if do_follow and follow:
                self._record_interaction_log(
                    params,
                    action="follow",
                    ok=bool(follow.get("ok")),
                    target_user_id=str(target.get("user_id") or "") or None,
                    target_nickname=str(target.get("nickname") or "") or None,
                    error_message=None if follow.get("ok") else str(follow.get("error") or ""),
                    raw_result=result if not follow.get("ok") else None,
                )
            return {
                "type": "builtin",
                "handler": "warm_outreach_from_comment",
                "status": "completed" if ok else "failed",
                "platform": self.platform,
                "comment_id": params.get("comment_id"),
                "content_url": content_url,
                "profile_url": result.get("profile_url"),
                "user_id": result.get("user_id") or params.get("user_id"),
                "username": params.get("username") or params.get("nickname"),
                "dry_run": result.get("dry_run"),
                "steps": result.get("steps"),
                "follow": follow,
                "dm": result.get("dm") or {"ok": False, "skipped": True, "reason": "xhs_pc_no_dm"},
                "error": None if ok else result.get("error"),
            }

        from app.services.social_roam.human.douyin.warm_outreach_profile import (
            warm_outreach_follow_dm_from_comment,
        )

        message = str(params.get("message") or params.get("dm_text") or "").strip()
        do_dm = bool(params.get("do_dm", True))
        if do_dm and not message:
            return {"error": "warm_outreach 私信需要 message", "status": "failed"}

        result = await warm_outreach_follow_dm_from_comment(
            page,
            self.settings,
            tenant_id=self.tenant_id,
            account_id=self.session.account_id,
            content_url=content_url,
            comment_id=str(target.get("comment_id") or ""),
            comment_text=str(target.get("comment_text") or ""),
            sec_uid=str(target.get("sec_uid") or ""),
            user_id=str(target.get("user_id") or ""),
            nickname=str(target.get("nickname") or ""),
            message=message,
            do_follow=bool(params.get("do_follow", True)),
            do_dm=do_dm,
            dry_run=dry_run,
            scroll_rounds=int(params.get("scroll_rounds") or 12),
        )
        ok = bool(result.get("ok"))
        follow = result.get("follow") or {}
        dm = result.get("dm") or {}
        if bool(params.get("do_follow", True)) and follow:
            self._record_interaction_log(
                params,
                action="follow",
                ok=bool(follow.get("ok")),
                target_user_id=str(params.get("user_id") or "") or None,
                target_sec_uid=str(params.get("sec_uid") or "") or None,
                target_nickname=str(params.get("username") or params.get("nickname") or "") or None,
                error_message=None if follow.get("ok") else str(follow.get("error") or ""),
                raw_result=result if not follow.get("ok") else None,
            )
        if do_dm and dm:
            self._record_interaction_log(
                params,
                action="dm",
                ok=bool(dm.get("ok")),
                target_user_id=str(params.get("user_id") or "") or None,
                target_sec_uid=str(params.get("sec_uid") or "") or None,
                target_nickname=str(params.get("username") or params.get("nickname") or "") or None,
                reply_text=message,
                error_message=None if dm.get("ok") else str(dm.get("error") or ""),
                raw_result=result if not dm.get("ok") else None,
            )
        return {
            "type": "builtin",
            "handler": "warm_outreach_from_comment",
            "status": "completed" if ok else "failed",
            "platform": self.platform,
            "comment_id": params.get("comment_id"),
            "content_url": content_url,
            "profile_url": result.get("profile_url"),
            "sec_uid": result.get("sec_uid") or params.get("sec_uid"),
            "user_id": result.get("user_id") or params.get("user_id"),
            "username": params.get("username") or params.get("nickname"),
            "dry_run": result.get("dry_run"),
            "steps": result.get("steps"),
            "follow": follow,
            "dm": dm,
            "error": None if ok else result.get("error"),
        }

    async def _execute_follow(self, params: dict[str, Any], *, action: str) -> dict[str, Any]:
        if (
            action == "follow"
            and self.platform in {"douyin", "xiaohongshu"}
            and self._warm_outreach_requested(params)
        ):
            warm_params = {**params, "do_dm": False, "do_follow": True}
            if self.platform == "xiaohongshu":
                warm_params["do_dm"] = False
            return await self._execute_warm_outreach_from_comment(warm_params)
        if self.platform == "xiaohongshu":
            if not str(params.get("user_id") or "").strip():
                return {"error": "缺少 user_id", "status": "failed"}
            return {
                "error": "小红书 Direct API 关注/取关已移除，请使用 warm_outreach（需 comment_id、content_url 与浏览器 page）",
                "status": "failed",
            }
        tool = get_follow_tool(
            self.settings,
            self.platform,
            self.tenant_id,
            account_id=self.session.account_id,
        )
        show_browser = self._resolve_show_browser(params)
        ui_first = bool(params.get("ui_first", False))
        username = str(params.get("username") or "")
        user_id = str(params.get("user_id") or "")
        sec_uid = str(params.get("sec_uid") or "")

        if self.platform == "douyin":
            if not sec_uid or not user_id:
                return {"error": "抖音关注需要 sec_uid 与 user_id", "status": "failed"}
            page = self.session.page if self.session.is_started else None
            if page is not None and show_browser:
                from app.services.social_roam.human.douyin.actions import human_follow_user

                result = await human_follow_user(
                    page,
                    self.settings,
                    tenant_id=self.tenant_id,
                    account_id=self.session.account_id,
                    sec_uid=sec_uid,
                    user_id=user_id,
                    username=username,
                )
                relation = {"ok": bool(result.get("ok")), **result}
                if action == "follow":
                    result = {**result, "follow": relation}
                else:
                    result = {**result, "unfollow": relation}
            elif ui_first or not show_browser:
                return {
                    "error": "抖音 JS API 关注/取关已移除，请使用 warm_outreach 或 show_browser=true 走 human UI",
                    "status": "failed",
                }
            else:
                return {
                    "error": "抖音关注需要有头浏览器 page，请启用 show_browser 或使用 warm_outreach",
                    "status": "failed",
                }
        else:
            if not user_id:
                return {"error": "缺少 user_id", "status": "failed"}
            if action == "follow":
                result = await tool.follow_user(
                    user_id=user_id,
                    username=username,
                    show_browser=show_browser,
                )
            else:
                result = await tool.unfollow_user(
                    user_id=user_id,
                    username=username,
                    show_browser=show_browser,
                )

        relation = result.get(action) or {}
        ok = bool(relation.get("ok"))
        self._record_interaction_log(
            params,
            action=action,
            ok=ok,
            target_user_id=str(result.get("user_id") or user_id or "") or None,
            target_sec_uid=str(result.get("sec_uid") or sec_uid or "") or None,
            target_nickname=str(result.get("username") or username or "") or None,
            error_message=None if ok else str(relation.get("error") or relation.get("reason") or ""),
            raw_result=result if not ok else None,
        )
        return {
            "type": "builtin",
            "handler": f"{action}_user",
            "status": "completed" if ok else "failed",
            "platform": self.platform,
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "sec_uid": result.get("sec_uid"),
            "profile_url": result.get("profile_url")
            or self._profile_url(self.platform, user_id, sec_uid or None),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            action: relation,
            "output_file": result.get("output_file"),
            "error": None if ok else relation.get("error") or relation.get("reason"),
        }

    async def _execute_send_dm(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.platform == "xiaohongshu":
            return {
                "error": "小红书 PC 网页版不支持私信",
                "status": "failed",
                "platform": self.platform,
            }
        if self.platform == "douyin" and self._warm_outreach_requested(params):
            return await self._execute_warm_outreach_from_comment(params)

        message = str(params.get("message") or "").strip()
        if not message:
            return {"error": "缺少 message", "status": "failed"}
        tool = get_dm_tool(
            self.settings,
            self.platform,
            self.tenant_id,
            account_id=self.session.account_id,
        )
        show_browser = self._resolve_show_browser(params)
        ui_first = bool(params.get("ui_first", False))
        username = str(params.get("username") or "")

        if self.platform == "douyin":
            sec_uid = str(params.get("sec_uid") or "")
            if not sec_uid:
                return {"error": "抖音私信需要 sec_uid", "status": "failed"}
            page = self.session.page if self.session.is_started else None
            if page is not None and show_browser:
                from app.services.social_roam.human.douyin.actions import human_send_dm

                result = await human_send_dm(
                    page,
                    self.settings,
                    tenant_id=self.tenant_id,
                    account_id=self.session.account_id,
                    sec_uid=sec_uid,
                    message=message,
                    username=username,
                )
                user_id = result.get("user_id")
                sec_uid_val = sec_uid
                dm = {"ok": bool(result.get("ok")), **{k: v for k, v in result.items() if k != "ok"}}
                result = {
                    "platform": self.platform,
                    "username": result.get("username") or username,
                    "user_id": user_id,
                    "sec_uid": sec_uid_val,
                    "profile_url": result.get("profile_url"),
                    "message": dm,
                }
            elif ui_first:
                return {
                    "error": "ui_first 模式下私信需有头浏览器 UI 操作",
                    "status": "failed",
                }
            else:
                result = await tool.send_message(
                    sec_uid=sec_uid,
                    message=message,
                    username=username,
                    show_browser=show_browser,
                )
                user_id = result.get("user_id")
                sec_uid_val = sec_uid
        else:
            user_id = str(params.get("user_id") or "")
            if not user_id:
                return {"error": "缺少 user_id", "status": "failed"}
            result = await tool.send_message(
                user_id=user_id,
                message=message,
                username=username,
                show_browser=show_browser,
            )
            sec_uid_val = result.get("sec_uid")

        dm = result.get("message") or {}
        ok = bool(dm.get("ok"))
        self._record_interaction_log(
            params,
            action="dm",
            ok=ok,
            target_user_id=str(result.get("user_id") or user_id or "") or None,
            target_sec_uid=str(result.get("sec_uid") or sec_uid_val or "") or None,
            target_nickname=str(result.get("username") or username or "") or None,
            reply_text=message,
            error_message=None if ok else str(dm.get("error") or dm.get("hint") or ""),
            raw_result=result if not ok else None,
        )
        return {
            "type": "builtin",
            "handler": "send_dm",
            "status": "completed" if ok else "failed",
            "platform": self.platform,
            "username": result.get("username"),
            "user_id": result.get("user_id") or user_id,
            "sec_uid": result.get("sec_uid") or sec_uid_val,
            "profile_url": result.get("profile_url")
            or self._profile_url(self.platform, str(user_id or ""), sec_uid_val),
            "message": dm,
            "output_file": result.get("output_file"),
            "error": None if ok else dm.get("error") or dm.get("hint"),
        }

    def _execute_query_stored_comments(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.db_session is None:
            return {"error": "查询已入库评论需要数据库会话", "status": "failed"}

        from app.platforms.types import normalize_platform
        from app.services.stored_comment_service import StoredCommentService

        platform = normalize_platform(str(params.get("platform") or self.platform))
        service = StoredCommentService(self.db_session, self.settings, tenant_id=self.tenant_id)
        query_type = str(params.get("query_type") or "comments").strip().lower()
        offset = int(params.get("offset") or 0)
        limit = int(params.get("limit") or 20)

        if query_type == "contents":
            result = service.query_contents(platform=platform, offset=offset, limit=limit)
        else:
            content_id = str(params.get("content_id") or "").strip() or None
            comment_text_contains = str(params.get("comment_text_contains") or "").strip() or None
            result = service.query_comments(
                platform=platform,
                content_id=content_id,
                comment_text_contains=comment_text_contains,
                offset=offset,
                limit=limit,
            )
        return {
            "status": "completed",
            "handler": "query_stored_comments",
            "platform": platform,
            "summary": f"已从数据库查询 {result.get('count', result.get('total', 0))} 条记录",
            "result": result,
        }

    def _execute_query_interaction_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.db_session is None:
            return {"error": "查询互动台账需要数据库会话", "status": "failed"}

        from app.platforms.types import normalize_platform

        platform = normalize_platform(str(params.get("platform") or self.platform))
        service = self._interaction_log_service()
        query_type = str(params.get("query_type") or "stats").strip().lower()
        period = str(params.get("period") or "today").strip().lower()
        account_id = str(params.get("account_id") or self.session.account_id or "").strip() or None
        offset = int(params.get("offset") or 0)
        limit = int(params.get("limit") or 20)

        if query_type == "logs":
            result = service.query_logs(
                platform=platform,
                action=str(params.get("action") or "").strip() or None,
                comment_id=str(params.get("comment_id") or "").strip() or None,
                target_user_id=str(params.get("target_user_id") or "").strip() or None,
                period=period,
                account_id=account_id,
                offset=offset,
                limit=limit,
            )
            summary = f"已查询 {result.get('total', 0)} 条互动记录"
        else:
            reply_limit = params.get("reply_limit")
            follow_limit = params.get("follow_limit")
            dm_limit = params.get("dm_limit")
            result = service.query_stats(
                platform=platform,
                account_id=account_id,
                period=period,
                reply_limit=int(reply_limit) if reply_limit is not None else None,
                follow_limit=int(follow_limit) if follow_limit is not None else None,
                dm_limit=int(dm_limit) if dm_limit is not None else None,
                comment_id=str(params.get("comment_id") or "").strip() or None,
                target_user_id=str(params.get("target_user_id") or "").strip() or None,
                target_sec_uid=str(params.get("target_sec_uid") or "").strip() or None,
            )
            summary = (
                f"今日 reply {result['reply']['count']}/{result['reply']['limit']}，"
                f"follow {result['follow']['count']}/{result['follow']['limit']}"
            )

        return {
            "status": "completed",
            "handler": "query_interaction_stats",
            "platform": platform,
            "summary": summary,
            "result": result,
        }

    async def _execute_social_roam(self, params: dict[str, Any]) -> dict[str, Any]:
        from app.services.social_roam.handler import SocialRoamService

        if self.db_session is None:
            return {"error": "social-roam 需要数据库会话（入库与 interaction_logs）", "status": "failed"}
        service = SocialRoamService(
            self.settings,
            self.tenant_id,
            self.platform,
            self.session,
            db_session=self.db_session,
        )
        return await service.execute(params)

    async def _execute_reply_comment(self, skill: SkillOut, params: dict[str, Any]) -> dict[str, Any]:
        comment_id = str(params.get("comment_id") or "").strip()
        reply_text = str(params.get("reply_text") or params.get("message") or "").strip()
        video_url = str(params.get("video_url") or params.get("content_url") or "").strip()
        comment_text = str(params.get("comment_text") or params.get("comment") or "").strip()
        if not reply_text:
            return {"error": "缺少 reply_text", "status": "failed"}
        if not comment_id and not (video_url and comment_text):
            return {"error": "缺少 comment_id，或同时提供 video_url + comment_text 用于 UI 定位", "status": "failed"}
        if self.db_session is None and not (video_url and comment_text):
            return {"error": "回复评论需要数据库会话或 UI 定位参数", "status": "failed"}

        from app.services.comment_reply_service import CommentReplyService

        service = CommentReplyService(
            self.settings,
            tenant_id=self.tenant_id,
            platform=self.platform,
            session=self.db_session,
            account_id=self.session.account_id,
        )
        show_browser = self._resolve_show_browser(params)
        page = self.session.page if self.session.is_started else None
        if page is not None:
            show_browser = True
        if (
            self.db_session is None
            and page is not None
            and video_url
            and comment_text
            and self.platform == "douyin"
        ):
            from app.services.social_roam.human.douyin.actions import human_reply_comment

            ui_result = await human_reply_comment(
                page,
                self.settings,
                tenant_id=self.tenant_id,
                content_url=video_url,
                reply_text=reply_text,
                comment_id=comment_id,
                comment_text=comment_text,
            )
            ok = bool(ui_result.get("ok"))
            return {
                "type": "builtin",
                "handler": "reply_comment",
                "status": "completed" if ok else "failed",
                "platform": self.platform,
                "comment_id": comment_id or ui_result.get("comment_id"),
                "content_url": video_url,
                "reply_text": reply_text,
                "summary": "已通过 UI 回复评论" if ok else f"UI 回复失败：{ui_result.get('error')}",
                "error": None if ok else ui_result.get("error"),
                "capture_method": ui_result.get("capture_method"),
            }
        warm_publish = bool(
            params.get("warm_publish")
            or str(params.get("reply_mode") or "").strip().lower() == "warm_publish"
            or (bool(params.get("ui_first")) and page is not None)
            or (
                page is not None
                and self.platform in ("douyin", "xiaohongshu")
                and params.get("warm_publish") is not False
            )
        )
        dry_run = bool(params.get("dry_run", False))
        try:
            result = await service.reply_comment(
                comment_id=comment_id,
                reply_text=reply_text,
                content_id=str(params.get("content_id") or "") or None,
                comment_text=str(params.get("comment_text") or params.get("comment_hint") or "") or None,
                video_url=str(params.get("video_url") or "") or None,
                note_url=str(params.get("note_url") or "") or None,
                content_url=str(params.get("content_url") or "") or None,
                photo_author_id=str(params.get("photo_author_id") or "") or None,
                reply_to_user_id=str(params.get("reply_to_user_id") or "") or None,
                show_browser=show_browser,
                page=page,
                prefer_human_ui=bool(params.get("prefer_human_ui", False)),
                ui_first=bool(params.get("ui_first", False)),
                warm_publish=warm_publish,
                dry_run=dry_run,
            )
        except LoginRequiredError as exc:
            return {"error": str(exc), "status": "failed"}
        except ValueError as exc:
            return {"error": str(exc), "status": "failed"}

        ok = result.get("status") == "completed"
        summary = (
            f"已回复评论 {comment_id}"
            if ok
            else f"回复评论失败：{result.get('error') or 'unknown'}"
        )
        self._record_interaction_log(
            params,
            action="reply",
            ok=ok,
            comment_id=comment_id,
            content_id=str(result.get("content_id") or params.get("content_id") or "") or None,
            content_url=str(result.get("content_url") or "") or None,
            reply_text=reply_text,
            error_message=str(result.get("error") or "") or None if not ok else None,
            raw_result=result if not ok else None,
        )
        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "type": "builtin",
            "handler": "reply_comment",
            "status": result.get("status") or ("completed" if ok else "failed"),
            "summary": summary,
            "platform": self.platform,
            "comment_id": comment_id,
            "content_id": result.get("content_id"),
            "content_url": result.get("content_url"),
            "reply_text": reply_text,
            "target_comment_text": result.get("target_comment_text"),
            "capture_method": result.get("capture_method"),
            "reply": result.get("reply"),
            "output_file": result.get("output_file"),
            "error": result.get("error"),
        }


def build_skill_tool_definitions(
    skills: list[SkillOut],
    *,
    explicit_skill_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    explicit = explicit_skill_ids or set()
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "list_skills",
                "description": "列出当前可用技能（仅含名称与描述）。需要执行某技能时调用 invoke_skill",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "invoke_skill",
                "description": "按 skill_id 调用技能；instruction 技能会注入完整操作指南，actions/builtin 会直接执行",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "description": "技能 ID，如 search-content"},
                        "params": {
                            "type": "object",
                            "description": "技能参数键值对",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["skill_id"],
                },
            },
        },
    ]
    skills_by_id = {s.id: s for s in skills}
    for skill in skills:
        if not skill.enabled:
            continue
        if skill.disable_model_invocation and skill.id not in explicit:
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in skill.parameters:
            schema: dict[str, Any] = {"type": param.type, "description": param.description}
            if param.default is not None:
                schema["default"] = param.default
            properties[param.name] = schema
            if param.required:
                required.append(param.name)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": skill.tool_name,
                    "description": f"[技能·自动] {skill.description}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return tools


def skills_description_summary(skills: list[SkillOut], explicit_skill_ids: set[str] | None = None) -> str:
    explicit = explicit_skill_ids or set()
    lines = []
    for skill in skills:
        if not skill.enabled:
            continue
        manual = skill.disable_model_invocation or skill.id in explicit
        tag = "手动" if manual else "自动"
        lines.append(f"- {skill.id} ({tag}): {skill.description}")
    return "\n".join(lines)
