from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.compat.envelope import CompatError


async def get_webcast_id(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    room_url = str(body.get("room_url") or body.get("share_url") or "").strip()
    if not room_url:
        raise CompatError("缺少 room_url", code=400)
    del settings, db, tenant_id, account_id
    return {"webcast_id": "", "room_url": room_url, "message": "live compat stub"}


async def fetch_user_live_videos(*args, **kwargs) -> dict[str, Any]:
    return {"data": [], "has_more": 0}


async def fetch_live_search(*args, **kwargs) -> dict[str, Any]:
    return {"data": [], "has_more": 0, "cursor": 0}
