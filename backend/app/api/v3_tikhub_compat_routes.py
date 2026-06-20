"""V3 TikHub-compatible routes — consumed by AISales HuokeCompatClient."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.deps_bridge import compat_account_id, compat_tenant_id, require_bridge_secret
from app.core.config import Settings, get_settings
from app.platforms.douyin.compat.live import fetch_live_search, fetch_user_live_videos, get_webcast_id
from app.platforms.douyin.compat.search_suggest import fetch_search_suggest
from app.platforms.douyin.compat.video_comments import fetch_video_comments
from app.platforms.douyin.compat.video_search import fetch_video_search
from app.services.compat.concurrency import compat_slot
from app.services.compat.envelope import CompatError, wrap, wrap_error
from app.services.compat.session_dispatcher import load_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/tikhub-compat", tags=["tikhub-compat"])

AdapterFn = Callable[..., Awaitable[dict[str, Any]]]


def _merge_debug_query(body: dict[str, Any], request: Request) -> dict[str, Any]:
    """?headed=1 或 ?debug=1 时合并进 body，仅显式触发有界面浏览器。"""
    merged = dict(body)
    for key in ("headed", "debug"):
        raw = request.query_params.get(key)
        if raw is not None and str(raw).strip().lower() in {"1", "true", "yes", "on"}:
            merged[key] = True
    return merged


async def _invoke_adapter(
    adapter: AdapterFn,
    request: Request,
    settings: Settings,
    db: Session,
    tenant_id: str,
    account_id: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if request.method.upper() in {"POST", "PUT", "PATCH"}:
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = {}
    body = _merge_debug_query(body, request)
    if body.get("headed") or body.get("debug") or body.get("show_browser"):
        logger.info(
            "compat headed request path=%s headed=%s show_browser=%s query=%s",
            request.url.path,
            body.get("headed"),
            body.get("show_browser"),
            dict(request.query_params),
        )
    search_source = str(body.get("source") or "auto").strip().lower()
    skip_login_for_hook = search_source in {"mobile_hook", "hook", "bridge", "auto"}
    session = load_session(settings, tenant_id=tenant_id, account_id=account_id, platform=_platform_for_adapter(adapter))
    status = session.login_status()
    # 抖音为 ready/incomplete；小红书 enrich 后为 authenticated
    login_ok_statuses = {"ready", "incomplete", "authenticated"}
    requires_login = _requires_login(adapter)
    if (
        requires_login
        and not (skip_login_for_hook and getattr(adapter, "__name__", "") == "fetch_video_search")
        and status.get("status") not in login_ok_statuses
    ):
        raise CompatError("平台 Cookie 未就绪，请先扫码登录", code=401)
    async with compat_slot(settings):
        data = await adapter(
            settings,
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            body=body,
        )
    return wrap(data)


def _platform_for_adapter(adapter: AdapterFn) -> str:
    module = getattr(adapter, "__module__", "") or ""
    if "xiaohongshu" in module:
        return "xiaohongshu"
    return "douyin"


def _requires_login(adapter: AdapterFn) -> bool:
    # search_suggest / live stubs 不强制登录
    name = getattr(adapter, "__name__", "")
    return name not in {"fetch_search_suggest", "get_webcast_id", "fetch_user_live_videos", "fetch_live_search"}


def _route(path: str, adapter: AdapterFn, *, methods: tuple[str, ...] = ("POST",)):
    async def _handler(
        request: Request,
        settings: Settings = Depends(get_settings),
        db: Session = Depends(db_session),
        tenant_id: str = Depends(compat_tenant_id),
        account_id: str = Depends(compat_account_id),
        _: None = Depends(require_bridge_secret),
    ) -> dict[str, Any]:
        try:
            return await _invoke_adapter(adapter, request, settings, db, tenant_id, account_id)
        except CompatError as exc:
            return wrap_error(exc)
        except Exception as exc:
            return wrap_error(exc)

    for method in methods:
        router.add_api_route(
            path,
            _handler,
            methods=[method],
            include_in_schema=False,
        )


# ---- 抖音 ----
for _suffix in (
    "fetch_video_search_v1",
    "fetch_video_search_v2",
    "fetch_general_search_v1",
    "fetch_multi_search",
):
    _route(f"/api/v1/douyin/search/{_suffix}", fetch_video_search)

_route("/api/v1/douyin/app/v3/fetch_video_comments", fetch_video_comments)
_route("/api/v1/douyin/search/fetch_user_search", fetch_video_search)
_route("/api/v1/douyin/web/fetch_user_post_videos", fetch_video_search)
_route("/api/v1/douyin/search/fetch_search_suggest", fetch_search_suggest)
_route("/api/v1/douyin/live/get_webcast_id", get_webcast_id)
_route("/api/v1/douyin/web/fetch_user_live_videos", fetch_user_live_videos)
for _live_suffix in ("fetch_live_search_v1", "fetch_live_search_v4"):
    _route(f"/api/v1/douyin/search/{_live_suffix}", fetch_live_search)

# ---- 小红书 ----
from app.platforms.xiaohongshu.compat.search_notes import (  # noqa: E402
    get_note_comments,
    get_note_detail,
    get_note_sub_comments,
    get_user_info,
    get_user_posted_notes,
    search_notes,
    search_users,
)

_route("/api/v1/xiaohongshu/web/search_notes", search_notes)
_route("/api/v1/xiaohongshu/web/get_note_detail_by_id", get_note_detail)
_route("/api/v1/xiaohongshu/web/get_image_note_detail", get_note_detail)
_route("/api/v1/xiaohongshu/web/get_video_note_detail", get_note_detail)
_route("/api/v1/xiaohongshu/web/get_note_comments", get_note_comments)
_route("/api/v1/xiaohongshu/web/get_note_sub_comments", get_note_sub_comments)
_route("/api/v1/xiaohongshu/web/search_users", search_users)
_route("/api/v1/xiaohongshu/web/get_user_info", get_user_info)
_route("/api/v1/xiaohongshu/web/get_user_posted_notes", get_user_posted_notes)


@router.get("/health")
def compat_health(_: None = Depends(require_bridge_secret)) -> dict[str, Any]:
    return wrap({"status": "ok", "layer": "v3_tikhub_compat"})
