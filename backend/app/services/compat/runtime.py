from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.skill_runner_service import SkillRunnerService


def build_runner(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    platform: str,
) -> SkillRunnerService:
    return SkillRunnerService(
        settings,
        tenant_id,
        platform,
        account_id=account_id,
        db_session=db,
    )


async def execute_skill(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    platform: str,
    skill_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    runner = build_runner(settings, db, tenant_id=tenant_id, account_id=account_id, platform=platform)
    headless: bool | None = None
    if params.get("show_browser") in (True, 1) or str(params.get("show_browser", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        headless = False
    return await runner.execute(skill_id, params, headless=headless)
