from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_account_id, get_authenticated_tenant_id
from app.core.config import Settings, get_settings
from app.platforms.kuaishou.utils import build_profile_url
from app.schemas.crawl_cache import CacheMeta
from app.schemas.kuaishou_tools import (
    KuaishouFollowUserRequest,
    KuaishouKeywordCommentsRequest,
    KuaishouSearchVideosRequest,
    KuaishouSendMessageRequest,
    KuaishouToolResponse,
    KuaishouUnfollowUserRequest,
    KuaishouVideoCommentsRequest,
)
from app.services.platform_skill_adapter import PlatformSkillAdapter
from app.services.skill_runner_service import SkillRunnerService

router = APIRouter(prefix="/api/platforms/kuaishou", tags=["kuaishou-tools"])


def _runner(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(db_session),
) -> SkillRunnerService:
    return SkillRunnerService(
        settings,
        tenant_id,
        "kuaishou",
        account_id=account_id,
        db_session=session,
    )


def _adapter(runner: SkillRunnerService = Depends(_runner)) -> PlatformSkillAdapter:
    return PlatformSkillAdapter(runner)


def _envelope(
    *,
    ok: bool,
    tenant_id: str,
    account_id: str,
    tool: str,
    data: dict,
    diagnostic: str | None = None,
    report_file: str | None = None,
    cache: CacheMeta | None = None,
) -> KuaishouToolResponse:
    return KuaishouToolResponse(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool=tool,
        data=data,
        diagnostic=diagnostic,
        report_file=report_file,
        cache=cache,
    )


@router.post("/search/videos", response_model=KuaishouToolResponse, summary="关键词搜索视频")
async def search_videos(
    payload: KuaishouSearchVideosRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output, cache_meta = await adapter.search(payload)
    videos = result.get("videos") or []
    return _envelope(
        ok=bool(videos),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="search",
        data={
            "keyword": payload.keyword,
            "search_keyword": result.get("search_keyword"),
            "region": payload.region,
            "days": payload.days,
            "video_count": len(videos),
            "capture_method": result.get("capture_method"),
            "videos": videos,
        },
        diagnostic=result.get("diagnostic"),
        report_file=str(output) if output else None,
        cache=cache_meta,
    )


@router.post("/comments/videos", response_model=KuaishouToolResponse, summary="抓取单视频评论")
async def crawl_video_comments(
    payload: KuaishouVideoCommentsRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, output, cache_meta = await adapter.crawl_content_comments(payload)
    comments = result.get("comments_preview") or []
    return _envelope(
        ok=bool(comments) or int(result.get("api_total_top_comments") or 0) == 0,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="comments",
        data={
            "photo_id": result.get("photo_id") or result.get("note_id"),
            "video_url": result.get("video_url") or result.get("note_url"),
            "total_comments_captured": result.get("total_comments_captured", 0),
            "api_total_top_comments": result.get("api_total_top_comments", 0),
            "capture_method": result.get("capture_method"),
            "comments_preview": comments,
            "comments_total_in_response": len(comments),
        },
        diagnostic=result.get("warning"),
        report_file=str(output) if output else None,
        cache=cache_meta,
    )


@router.post("/comments/keyword", response_model=KuaishouToolResponse, summary="关键词搜索并抓取评论")
async def crawl_keyword_comments(
    payload: KuaishouKeywordCommentsRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result, diagnostic, cache_meta = await adapter.crawl_keyword_comments(payload)
    items = result.get("items") or []
    return _envelope(
        ok=bool(items),
        tenant_id=tenant_id,
        account_id=account_id,
        tool="comments_keyword",
        data={
            "keyword": payload.keyword,
            "videos_found": len(items),
            "session_mode": result.get("session_mode", "logged_in"),
            "items": items,
        },
        diagnostic=diagnostic,
        cache=cache_meta,
    )


@router.post("/users/follow", response_model=KuaishouToolResponse, summary="关注单个用户")
async def follow_user(
    payload: KuaishouFollowUserRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await adapter.follow_user(payload)
    follow = result.get("follow") or {}
    ok = bool(follow.get("ok"))
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="follow",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "profile_url": result.get("profile_url") or build_profile_url(payload.user_id),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            "follow": follow,
        },
        diagnostic=follow.get("error") or follow.get("reason") or result.get("error"),
        report_file=result.get("output_file"),
    )


@router.post("/users/unfollow", response_model=KuaishouToolResponse, summary="取消关注单个用户")
async def unfollow_user(
    payload: KuaishouUnfollowUserRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await adapter.unfollow_user(payload)
    unfollow = result.get("unfollow") or {}
    ok = bool(unfollow.get("ok"))
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="unfollow",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "profile_url": result.get("profile_url") or build_profile_url(payload.user_id),
            "follow_status_before": result.get("follow_status_before"),
            "follow_status_after": result.get("follow_status_after"),
            "unfollow": unfollow,
        },
        diagnostic=unfollow.get("error") or unfollow.get("reason") or result.get("error"),
        report_file=result.get("output_file"),
    )


@router.post("/users/messages", response_model=KuaishouToolResponse, summary="向单个用户发送私信")
async def send_user_message(
    payload: KuaishouSendMessageRequest,
    adapter: PlatformSkillAdapter = Depends(_adapter),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
):
    result = await adapter.send_message(payload)
    message = result.get("message") or {}
    ok = bool(message.get("ok"))
    return _envelope(
        ok=ok,
        tenant_id=tenant_id,
        account_id=account_id,
        tool="dm",
        data={
            "username": result.get("username"),
            "user_id": result.get("user_id"),
            "profile_url": result.get("profile_url") or build_profile_url(payload.user_id),
            "message": message,
            "text_preview": payload.message[:80],
        },
        diagnostic=message.get("error") or message.get("hint") or result.get("error"),
        report_file=result.get("output_file"),
    )
