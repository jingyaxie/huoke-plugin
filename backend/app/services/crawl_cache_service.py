from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.crawl_cache_repository import CrawlCacheRepository
from app.schemas.crawl_cache import DEFAULT_CACHE_TTL_HOURS, CacheMeta


def normalize_cache_params(params: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, (list, tuple)):
            cleaned[key] = sorted(str(v) for v in value)
        else:
            cleaned[key] = str(value)
    return cleaned


def build_params_hash(params: dict[str, Any]) -> str:
    normalized = normalize_cache_params(params)
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_cache_key(operation: str, tenant_id: str, platform: str, account_id: str, params: dict[str, Any]) -> str:
    digest = build_params_hash(params)
    return f"{operation}:{tenant_id}:{platform}:{account_id}:{digest}"


@dataclass
class CacheLookupResult:
    payload: dict[str, Any]
    file_path: Path | None
    meta: CacheMeta


class CrawlCacheService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        tenant_id: str,
        platform: str,
        account_id: str = "default",
    ) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.account_id = account_id
        self.repo = CrawlCacheRepository(session, tenant_id, platform)

    def lookup(
        self,
        operation: str,
        params: dict[str, Any],
        *,
        force_refresh: bool = False,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
    ) -> CacheLookupResult | None:
        if force_refresh:
            return None
        cache_key = build_cache_key(operation, self.tenant_id, self.platform, self.account_id, params)
        row = self.repo.get_by_key(cache_key)
        if row is None:
            return None
        now = datetime.utcnow()
        if row.expires_at <= now:
            return None
        self.repo.touch_hit(row)
        file_path = Path(row.file_path) if row.file_path else None
        meta = CacheMeta(
            from_cache=True,
            cache_hit=True,
            cached_at=row.fetched_at,
            fetched_at=row.fetched_at,
            expires_at=row.expires_at,
        )
        return CacheLookupResult(payload=dict(row.payload_json or {}), file_path=file_path, meta=meta)

    def lookup_stale(self, operation: str, params: dict[str, Any]) -> CacheLookupResult | None:
        """返回已有缓存（含已过期），用于强制拉取失败时的回退。"""
        cache_key = build_cache_key(operation, self.tenant_id, self.platform, self.account_id, params)
        row = self.repo.get_by_key(cache_key)
        if row is None:
            return None
        file_path = Path(row.file_path) if row.file_path else None
        meta = CacheMeta(
            from_cache=True,
            cache_hit=True,
            cached_at=row.fetched_at,
            fetched_at=row.fetched_at,
            expires_at=row.expires_at,
        )
        return CacheLookupResult(payload=dict(row.payload_json or {}), file_path=file_path, meta=meta)

    def store(
        self,
        operation: str,
        params: dict[str, Any],
        payload: dict[str, Any],
        *,
        file_path: Path | str | None = None,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        incremental_merge: bool = False,
        new_comments_added: int = 0,
        updated_comments: int = 0,
    ) -> CacheMeta:
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=cache_ttl_hours)
        cache_key = build_cache_key(operation, self.tenant_id, self.platform, self.account_id, params)
        params_hash = build_params_hash(params)
        payload_to_store = dict(payload)
        payload_to_store["cache_meta"] = {
            "from_cache": False,
            "fetched_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "incremental_merge": incremental_merge,
            "new_comments_added": new_comments_added,
            "updated_comments": updated_comments,
        }
        self.repo.upsert(
            cache_key=cache_key,
            operation=operation,
            tenant_id=self.tenant_id,
            platform=self.platform,
            account_id=self.account_id,
            params_hash=params_hash,
            params_json=normalize_cache_params(params),
            payload_json=payload_to_store,
            file_path=str(file_path) if file_path else None,
            fetched_at=now,
            expires_at=expires_at,
        )
        return CacheMeta(
            from_cache=False,
            cache_hit=False,
            fetched_at=now,
            expires_at=expires_at,
            incremental_merge=incremental_merge,
            new_comments_added=new_comments_added,
            updated_comments=updated_comments,
        )

    def attach_meta(self, payload: dict[str, Any], meta: CacheMeta) -> dict[str, Any]:
        merged = dict(payload)
        merged["cache_meta"] = meta.model_dump(mode="json")
        return merged
