from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.antibot import LoginRequiredError, require_login
from app.platforms.douyin.session import DouyinSessionStore
from app.services.agent_browser_session import AgentBrowserSession
from app.services.comment_store_service import CommentStoreService, extract_content_id
from app.services.interaction_log_service import ENGINE_SOCIAL_ROAM, InteractionLogService
from app.platforms.douyin.human_guards import HumanBrowseGuardError
from app.services.social_roam.human.douyin.actions import (
    browse_keyword_comments,
    human_follow_user,
    human_reply_comment,
)
from app.services.outreach_matcher import (
    action_enabled,
    match_spec,
    reply_template,
    resolve_follow_match,
)
from app.services.outreach_normalizer import normalize_crawl_results
from app.services.social_roam.types import SocialRoamParams, parse_social_roam_params, render_template
from app.services.outreach_policy import random_interval_sec
from app.core.config import Settings


class SocialRoamService:
    """social-roam builtin：全人工读+写链路（Phase 2 MVP，抖音 keyword）。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        platform: str,
        session: AgentBrowserSession,
        db_session: Session | None = None,
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.session = session
        self.db_session = db_session

    async def execute(self, raw_params: dict[str, Any]) -> dict[str, Any]:
        params = parse_social_roam_params(raw_params, platform=self.platform)
        if params.platform != "douyin":
            return {"status": "failed", "error": f"Phase 2 MVP 暂仅支持 douyin，当前: {params.platform}"}
        if params.browse_mode != "keyword":
            return {"status": "failed", "error": f"Phase 2 MVP 暂仅支持 browse.mode=keyword，当前: {params.browse_mode}"}
        if not params.keyword:
            return {"status": "failed", "error": "缺少 keyword 或 browse.keyword"}

        store = DouyinSessionStore(self.settings)
        try:
            require_login(store, self.tenant_id, self.settings, account_id=self.session.account_id)
        except LoginRequiredError as exc:
            return {"status": "failed", "error": str(exc)}

        task_id = params.task_id or uuid.uuid4().hex[:16]
        if params.show_browser:
            self.session.headless = False
        page = await self.session.ensure_started()

        try:
            results, diagnostic = await browse_keyword_comments(
                self.settings,
                tenant_id=self.tenant_id,
                account_id=self.session.account_id,
                keyword=params.keyword,
                content_limit=params.content_limit,
                days=params.days,
                region=params.region,
                page=page,
                show_browser=True,
            )
        except HumanBrowseGuardError as exc:
            return {
                "status": "failed",
                "handler": "social_roam",
                "error": str(exc),
                "code": "human_guard_failed",
                "task_id": task_id,
            }
        if not results:
            return {
                "status": "failed",
                "handler": "social_roam",
                "error": diagnostic or "未抓取到任何视频评论",
                "task_id": task_id,
            }

        if params.persist_to_db and self.db_session is not None:
            self._persist_results(results)

        leads = normalize_crawl_results(
            results,
            task_id=task_id,
            keyword=params.keyword,
            platform=params.platform,
        )[: params.max_comments_scanned]

        stats = {
            "contents": len(results),
            "comments_scanned": len(leads),
            "replies": 0,
            "follows": 0,
            "skipped": 0,
            "dry_run": params.dry_run,
        }
        seen_users: set[str] = set()
        log_service = InteractionLogService(self.db_session, self.settings, tenant_id=self.tenant_id) if self.db_session else None
        template = reply_template(params.actions_on_match)
        daily_reply_cap = int(params.limits.get("daily_max_replies") or params.limits.get("max_comment_replies") or params.max_replies)
        daily_follow_cap = int(params.limits.get("daily_max_follows") or params.limits.get("max_follows") or params.max_follows)

        for lead in leads:
            comment_text = lead["comment"]["text"]
            reply_ok, reply_reason = match_spec(comment_text, params.comment_match)
            follow_ok, follow_reason = resolve_follow_match(
                comment_text,
                params.comment_match,
                params.follow_match,
            )
            lead["matched"] = reply_ok or follow_ok
            lead["match_reason"] = reply_reason if reply_ok else follow_reason

            if stats["replies"] >= params.max_replies and stats["follows"] >= params.max_follows:
                break

            user_key = lead["comment_user"].get("user_id") or lead["comment_user"].get("sec_uid") or ""
            if params.dedupe_user_per_task and user_key and user_key in seen_users:
                stats["skipped"] += 1
                continue

            if reply_ok and action_enabled(params.actions_on_match, "reply") and stats["replies"] < params.max_replies:
                if log_service:
                    quota = log_service.query_stats(
                        platform=params.platform,
                        account_id=self.session.account_id,
                        period="today",
                        reply_limit=daily_reply_cap,
                        follow_limit=daily_follow_cap,
                    )
                    if not quota["reply"]["quota_ok"]:
                        stats["stop_reason"] = "daily_reply_quota_exhausted"
                        break
                comment_id = lead["comment"]["comment_id"]
                if log_service and log_service.is_comment_replied(platform=params.platform, comment_id=comment_id):
                    stats["skipped"] += 1
                    lead["actions_taken"].append({"type": "reply", "status": "skipped", "error": "already_replied"})
                else:
                    reply_text = render_template(
                        template,
                        nickname=lead["comment_user"]["nickname"],
                        comment=comment_text,
                    )
                    if params.dry_run:
                        lead["actions_taken"].append({"type": "reply", "status": "dry_run", "reply_text": reply_text})
                        stats["replies"] += 1
                    else:
                        result = await human_reply_comment(
                            page,
                            self.settings,
                            tenant_id=self.tenant_id,
                            content_url=lead["content"]["content_url"],
                            comment_id=comment_id,
                            reply_text=reply_text,
                        )
                        ok = bool(result.get("ok"))
                        if log_service:
                            log_service.record(
                                platform=params.platform,
                                action="reply",
                                status="ok" if ok else "failed",
                                engine=ENGINE_SOCIAL_ROAM,
                                account_id=self.session.account_id,
                                comment_id=comment_id,
                                content_id=lead["content"]["content_id"],
                                content_url=lead["content"]["content_url"],
                                target_user_id=lead["comment_user"].get("user_id"),
                                target_sec_uid=lead["comment_user"].get("sec_uid"),
                                target_nickname=lead["comment_user"].get("nickname"),
                                keyword=params.keyword,
                                task_id=task_id,
                                reply_text=reply_text,
                                error_message=result.get("error"),
                                raw_result=result,
                            )
                        lead["actions_taken"].append(
                            {"type": "reply", "status": "ok" if ok else "failed", "error": result.get("error")}
                        )
                        if ok:
                            stats["replies"] += 1
                            if user_key:
                                seen_users.add(user_key)
                            await asyncio.sleep(
                                random_interval_sec(params.interval_min_sec, params.interval_max_sec)
                            )

            if (
                follow_ok
                and action_enabled(params.actions_on_match, "follow")
                and stats["follows"] < params.max_follows
            ):
                if log_service:
                    quota = log_service.query_stats(
                        platform=params.platform,
                        account_id=self.session.account_id,
                        period="today",
                        reply_limit=daily_reply_cap,
                        follow_limit=daily_follow_cap,
                    )
                    if not quota["follow"]["quota_ok"]:
                        stats["stop_reason"] = "daily_follow_quota_exhausted"
                        break
                sec_uid = lead["comment_user"].get("sec_uid") or ""
                user_id = lead["comment_user"].get("user_id") or ""
                if not sec_uid or not user_id:
                    lead["actions_taken"].append({"type": "follow", "status": "skipped", "error": "missing_user_ids"})
                elif log_service and log_service.is_user_followed(
                    platform=params.platform,
                    target_user_id=user_id,
                    target_sec_uid=sec_uid,
                ):
                    stats["skipped"] += 1
                    lead["actions_taken"].append({"type": "follow", "status": "skipped", "error": "already_followed"})
                elif params.dry_run:
                    lead["actions_taken"].append({"type": "follow", "status": "dry_run"})
                    stats["follows"] += 1
                else:
                    result = await human_follow_user(
                        page,
                        self.settings,
                        tenant_id=self.tenant_id,
                        account_id=self.session.account_id,
                        sec_uid=sec_uid,
                        user_id=user_id,
                        username=lead["comment_user"].get("nickname") or "",
                    )
                    ok = bool(result.get("ok"))
                    if log_service:
                        log_service.record(
                            platform=params.platform,
                            action="follow",
                            status="ok" if ok else "failed",
                            engine=ENGINE_SOCIAL_ROAM,
                            account_id=self.session.account_id,
                            target_user_id=user_id,
                            target_sec_uid=sec_uid,
                            target_nickname=lead["comment_user"].get("nickname"),
                            keyword=params.keyword,
                            task_id=task_id,
                            error_message=result.get("error"),
                            raw_result=result,
                        )
                    lead["actions_taken"].append(
                        {"type": "follow", "status": "ok" if ok else "failed", "error": result.get("error")}
                    )
                    if ok:
                        stats["follows"] += 1
                        if user_key:
                            seen_users.add(user_key)
                        await asyncio.sleep(
                            random_interval_sec(params.interval_min_sec, params.interval_max_sec)
                        )

        output_path = self.settings.report_output_dir / f"social_roam_{params.platform}_{task_id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "task_id": task_id,
            "platform": params.platform,
            "keyword": params.keyword,
            "engine": ENGINE_SOCIAL_ROAM,
            "stats": stats,
            "diagnostic": diagnostic,
            "leads": leads,
        }
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = (
            f"social-roam 完成：{stats['contents']} 个视频，"
            f"扫描 {stats['comments_scanned']} 条评论，"
            f"回复 {stats['replies']}，关注 {stats['follows']}"
        )
        if params.dry_run:
            summary += "（dry_run）"
        return {
            "status": "completed",
            "handler": "social_roam",
            "platform": params.platform,
            "summary": summary,
            "task_id": task_id,
            "stats": stats,
            "output_file": str(output_path),
            "leads_count": len(leads),
            "matched_count": sum(1 for lead in leads if lead.get("matched")),
        }

    def _persist_results(self, results: list[dict[str, Any]]) -> None:
        if self.db_session is None:
            return
        store = CommentStoreService(self.db_session, self.settings, tenant_id=self.tenant_id)
        for payload in results:
            content_id = extract_content_id("douyin", payload.get("video_url") or "", payload)
            if not content_id:
                continue
            store.merge_and_persist(
                platform="douyin",
                content_id=content_id,
                content_url=str(payload.get("video_url") or ""),
                fetched_payload=payload,
            )
