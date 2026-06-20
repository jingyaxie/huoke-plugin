from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    db_session,
    effective_tenant_id,
    get_account_id,
    get_authenticated_tenant_id,
    require_path_tenant,
    resolve_path_platform_id,
)
from app.core.config import Settings, get_settings
from app.platforms.registry import get_hot_crawler, get_session_store, list_platforms
from app.schemas.comment_crawl import DouyinLoginRequest, UploadStorageStateRequest
from app.schemas.content_library import ContentDetailOut, ContentListResponse
from app.services.content_library_service import ContentLibraryService


router = APIRouter(prefix="/api")


@router.get("/platforms")
def supported_platforms():
    return {"platforms": list_platforms()}


@router.get("/platforms/{platform}/login-status")
def platform_login_status(
    platform: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    store = get_session_store(settings, pid)
    return store.login_status(tenant_id, account_id)


@router.post("/platforms/{platform}/login-status/verify", summary="在线校验并可选刷新登录态")
async def platform_verify_login_status(
    platform: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    refresh: bool = Query(default=False, description="校验通过时写回 storage_state 与 session_meta"),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    if pid != "xiaohongshu":
        store = get_session_store(settings, pid)
        status = store.login_status(tenant_id, account_id)
        return {
            "live_ok": status.get("status") == "ready",
            "refreshed": False,
            "platform": pid,
            **status,
            "message": status.get("message") or "该平台暂不支持在线校验，仅返回本地 Cookie 状态",
        }
    from app.platforms.xiaohongshu.persistence import verify_live_session

    store = get_session_store(settings, pid)
    result = await verify_live_session(settings, store, tenant_id, account_id, refresh=refresh)
    return {"platform": pid, "tenant_id": tenant_id, "account_id": account_id, **result}


@router.delete("/platforms/{platform}/login-session", summary="清除平台登录记录")
async def platform_clear_login_session(
    platform: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    account_id: str = Depends(get_account_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    from app.platforms.interactive_login import stop_interactive_session

    await stop_interactive_session(pid, tenant_id, account_id)
    store = get_session_store(settings, pid)
    cleared = store.clear_session(tenant_id, account_id)
    return {**cleared, **store.login_status(tenant_id, account_id)}


@router.put("/platforms/{platform}/tenants/{tenant_id}/storage-state")
def platform_upload_storage_state(
    platform: str,
    tenant_id: str,
    payload: UploadStorageStateRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    from app.platforms.registry import get_session_store

    store = get_session_store(settings, pid)
    path = store.save_dict(tid, payload.storage_state)
    status = store.login_status(tid)
    return {"platform": pid, "tenant_id": tid, "storage_state_path": str(path), **status}


@router.post("/platforms/{platform}/login")
async def platform_login(
    platform: str,
    payload: DouyinLoginRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    tid = effective_tenant_id(authenticated_tenant_id, payload.tenant_id, settings)
    crawler = get_hot_crawler(settings, pid, tid)
    await crawler.login_and_save_cookies(show_browser=payload.show_browser)
    store = get_session_store(settings, pid)
    return {"platform": pid, "tenant_id": tid, "storage_state_path": str(store.path_for(tid))}


@router.get("/platforms/{platform}/contents", response_model=ContentListResponse)
def platform_list_contents(
    platform: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    updated_after: datetime | None = Query(default=None, description="最后更新时间下限（含）"),
    updated_before: datetime | None = Query(default=None, description="最后更新时间上限（含）"),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    service = ContentLibraryService(session, settings, tenant_id=tenant_id)
    return service.list_contents(
        platform=pid,
        offset=offset,
        limit=limit,
        updated_after=updated_after,
        updated_before=updated_before,
    )


@router.get("/platforms/{platform}/contents/{content_id}", response_model=ContentDetailOut)
def platform_get_content_detail(
    platform: str,
    content_id: str,
    max_comments: int | None = Query(default=None, ge=1, le=2000),
    session: Session = Depends(db_session),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    pid = resolve_path_platform_id(platform)
    service = ContentLibraryService(session, settings, tenant_id=tenant_id)
    detail = service.get_content_detail(platform=pid, content_id=content_id, max_comments=max_comments)
    if detail is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return detail


@router.get("/comments/download")
def download_comment_file(file_name: str = Query(..., min_length=1)):
    settings = get_settings()
    safe_name = Path(file_name).name
    path = settings.report_output_dir / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Result file not found")
    return FileResponse(path, media_type="application/json", filename=safe_name)
