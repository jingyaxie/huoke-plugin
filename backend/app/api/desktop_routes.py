from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.core.config import Settings, get_settings
from app.schemas.desktop_maintenance import DesktopRepairResult
from app.services.desktop_maintenance_service import (
    export_desktop_diagnostics_zip,
    repair_desktop_runtime,
)


router = APIRouter(prefix="/api/desktop", tags=["desktop"])


def _require_desktop_mode(settings: Settings) -> None:
    if not settings.desktop_mode:
        raise HTTPException(status_code=404, detail="仅桌面模式可用")


@router.post("/repair", response_model=DesktopRepairResult)
def repair_desktop(settings: Settings = Depends(get_settings)) -> DesktopRepairResult:
    _require_desktop_mode(settings)
    result = repair_desktop_runtime(settings)
    return DesktopRepairResult.model_validate(result)


@router.get("/diagnostics")
def export_desktop_diagnostics(settings: Settings = Depends(get_settings)) -> Response:
    _require_desktop_mode(settings)
    content, filename = export_desktop_diagnostics_zip(settings)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=content, media_type="application/zip", headers=headers)
