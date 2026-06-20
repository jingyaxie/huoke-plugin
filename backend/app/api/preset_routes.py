from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_authenticated_tenant_id
from app.core.config import Settings, get_settings
from app.schemas.presets import (
    PresetCreateRequest,
    PresetKind,
    PresetListOut,
    PresetTemplate,
    PresetUpdateRequest,
)
from app.services.preset_store_service import PresetStoreService

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _store(settings: Settings, tenant_id: str) -> PresetStoreService:
    return PresetStoreService(settings, tenant_id)


@router.get("", response_model=PresetListOut)
def list_presets(
    kind: PresetKind = Query(...),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> PresetListOut:
    return _store(settings, tenant_id).list_presets(kind)


@router.post("", response_model=PresetTemplate)
def create_preset(
    payload: PresetCreateRequest,
    kind: PresetKind = Query(...),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> PresetTemplate:
    return _store(settings, tenant_id).create_preset(kind, payload)


@router.patch("/{preset_id}", response_model=PresetTemplate)
def update_preset(
    preset_id: str,
    payload: PresetUpdateRequest,
    kind: PresetKind = Query(...),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> PresetTemplate:
    try:
        return _store(settings, tenant_id).update_preset(kind, preset_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="预设不存在") from exc


@router.delete("/{preset_id}")
def delete_preset(
    preset_id: str,
    kind: PresetKind = Query(...),
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    deleted = _store(settings, tenant_id).delete_preset(kind, preset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="预设不存在")
    return {"deleted": True}
