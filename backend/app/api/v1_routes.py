from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import db_session, verify_admin_secret
from app.core.config import Settings, get_settings
from app.schemas.common import HealthResponse
from app.schemas.tenant import CreateTenantKeyRequest, CreateTenantKeyResponse
from app.services.tenant_auth_service import TenantAuthService


router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    index_file = settings.frontend_dist_dir / "index.html"
    frontend_available = settings.desktop_mode and index_file.is_file()
    status = "ok"
    if settings.desktop_mode and not frontend_available:
        status = "degraded"
    return HealthResponse(
        status=status,
        storage_root=str(settings.storage_root),
        desktop_mode=settings.desktop_mode,
        frontend_available=frontend_available,
    )


@router.post("/admin/tenant-keys", response_model=CreateTenantKeyResponse)
def create_tenant_api_key(
    payload: CreateTenantKeyRequest,
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(verify_admin_secret),
):
    auth = TenantAuthService(session, settings)
    api_key, row = auth.create_api_key(payload.tenant_id, label=payload.label)
    session.commit()
    return CreateTenantKeyResponse(
        tenant_id=row.tenant_id,
        api_key=api_key,
        label=row.label,
        message="请妥善保存 API Key，之后无法再次查看明文",
    )
