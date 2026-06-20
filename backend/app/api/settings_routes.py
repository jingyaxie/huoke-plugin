from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_authenticated_tenant_id
from app.core.config import Settings, get_settings
from app.schemas.interaction_settings import InteractionSettings, InteractionSettingsUpdate
from app.schemas.llm_settings import LlmSettingsOut, LlmSettingsUpdate, LlmSettingsUpdateResult
from app.schemas.page_diagnosis_settings import PageDiagnosisSettings, PageDiagnosisSettingsUpdate
from app.services.interaction_settings_service import InteractionSettingsService
from app.services.llm_settings_service import patch_cached_settings, read_llm_settings, save_llm_settings
from app.services.page_diagnosis_settings_service import PageDiagnosisSettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _can_edit_local_settings(settings: Settings) -> bool:
    if settings.desktop_mode:
        return True
    return str(settings.database_url or "").startswith("sqlite")


@router.get("/llm", response_model=LlmSettingsOut)
def get_llm_settings(settings: Settings = Depends(get_settings)) -> LlmSettingsOut:
    return LlmSettingsOut.model_validate(read_llm_settings(settings))


@router.get("/interaction", response_model=InteractionSettings)
def get_interaction_settings(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> InteractionSettings:
    return InteractionSettingsService(settings, tenant_id).read()


@router.put("/interaction", response_model=InteractionSettings)
def put_interaction_settings(
    payload: InteractionSettingsUpdate,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    settings: Settings = Depends(get_settings),
) -> InteractionSettings:
    return InteractionSettingsService(settings, tenant_id).save(payload)


@router.put("/llm", response_model=LlmSettingsUpdateResult)
def put_llm_settings(
    payload: LlmSettingsUpdate,
    settings: Settings = Depends(get_settings),
) -> LlmSettingsUpdateResult:
    if not _can_edit_local_settings(settings):
        raise HTTPException(
            status_code=403,
            detail="模型设置仅可在本机 Sidecar / 桌面模式修改",
        )
    result = save_llm_settings(settings, payload.model_dump(exclude_unset=True))
    patch_cached_settings(settings)
    return LlmSettingsUpdateResult.model_validate(result)


@router.get("/page-diagnosis", response_model=PageDiagnosisSettings)
def get_page_diagnosis_settings(
    settings: Settings = Depends(get_settings),
) -> PageDiagnosisSettings:
    return PageDiagnosisSettingsService(settings).read()


@router.put("/page-diagnosis", response_model=PageDiagnosisSettings)
def put_page_diagnosis_settings(
    payload: PageDiagnosisSettingsUpdate,
    settings: Settings = Depends(get_settings),
) -> PageDiagnosisSettings:
    if not _can_edit_local_settings(settings):
        raise HTTPException(
            status_code=403,
            detail="页面诊断设置仅可在本机 Sidecar / 桌面模式修改",
        )
    return PageDiagnosisSettingsService(settings).save(payload)
