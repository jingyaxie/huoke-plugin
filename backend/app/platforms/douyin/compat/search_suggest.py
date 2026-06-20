from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.compat.envelope import CompatError


async def fetch_search_suggest(
    settings: Settings,
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    keyword = str(body.get("keyword") or "").strip()
    if not keyword:
        raise CompatError("缺少 keyword", code=400)
    # 联想词暂无独立 Skill，返回关键词本身以满足契约探测。
    del settings, db, tenant_id, account_id
    return {"sug_list": [{"content": keyword, "word": keyword}], "words": [keyword]}
