from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_authenticated_tenant_id, require_path_tenant
from app.core.antibot import global_antibot_config, tenant_antibot_config
from app.core.config import Settings, get_settings
from app.schemas.antibot import (
    AntibotGlobalConfigOut,
    TenantAntibotConfigOut,
    TenantAntibotOverrideOut,
    TenantAntibotOverrideRequest,
)
from app.services.tenant_antibot_store import TenantAntibotStore


router = APIRouter(prefix="/api")


@router.get("/antibot/config", response_model=AntibotGlobalConfigOut)
def get_global_antibot_config(settings: Settings = Depends(get_settings)):
    return global_antibot_config(settings)


@router.get("/antibot/config/effective", response_model=TenantAntibotConfigOut)
def get_effective_antibot_config(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    return tenant_antibot_config(settings, tenant_id)


@router.get("/tenants/{tenant_id}/antibot", response_model=TenantAntibotConfigOut)
def get_tenant_antibot_config(
    tenant_id: str,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    return tenant_antibot_config(settings, tid)


@router.put("/tenants/{tenant_id}/antibot", response_model=TenantAntibotConfigOut)
def upsert_tenant_antibot_config(
    tenant_id: str,
    payload: TenantAntibotOverrideRequest,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    override = TenantAntibotOverrideOut.model_validate(payload.model_dump(exclude_unset=True))
    if override.delay_min_ms is not None and override.delay_max_ms is not None:
        if override.delay_max_ms < override.delay_min_ms:
            raise HTTPException(status_code=400, detail="delay_max_ms 不能小于 delay_min_ms")
    store = TenantAntibotStore(settings)
    data = override.model_dump(exclude_none=True)
    if not data:
        store.delete(tid)
    else:
        store.save(tid, override)
    return tenant_antibot_config(settings, tid)


@router.delete("/tenants/{tenant_id}/antibot", response_model=TenantAntibotConfigOut)
def delete_tenant_antibot_config(
    tenant_id: str,
    authenticated_tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
):
    tid = require_path_tenant(tenant_id, authenticated_tenant_id, settings)
    TenantAntibotStore(settings).delete(tid)
    return tenant_antibot_config(settings, tid)
