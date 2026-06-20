from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.models.crawl_cache import CrawlCacheEntry
from app.repositories.base import BaseRepository


class CrawlCacheRepository(BaseRepository):
    def get_by_key(self, cache_key: str) -> CrawlCacheEntry | None:
        return self.session.scalar(
            select(CrawlCacheEntry).where(CrawlCacheEntry.cache_key == cache_key).limit(1)
        )

    def upsert(
        self,
        *,
        cache_key: str,
        operation: str,
        tenant_id: str,
        platform: str,
        account_id: str,
        params_hash: str,
        params_json: dict,
        payload_json: dict,
        file_path: str | None,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> CrawlCacheEntry:
        row = self.get_by_key(cache_key)
        now = datetime.utcnow()
        if row is None:
            row = CrawlCacheEntry(
                cache_key=cache_key,
                operation=operation,
                tenant_id=tenant_id,
                platform=platform,
                account_id=account_id,
                params_hash=params_hash,
                params_json=params_json,
                payload_json=payload_json,
                file_path=file_path,
                fetched_at=fetched_at,
                expires_at=expires_at,
                last_accessed_at=now,
                hit_count=0,
            )
            self.session.add(row)
        else:
            row.operation = operation
            row.params_hash = params_hash
            row.params_json = params_json
            row.payload_json = payload_json
            row.file_path = file_path
            row.fetched_at = fetched_at
            row.expires_at = expires_at
            row.last_accessed_at = now
        self.session.flush()
        return row

    def touch_hit(self, row: CrawlCacheEntry) -> CrawlCacheEntry:
        row.hit_count = int(row.hit_count or 0) + 1
        row.last_accessed_at = datetime.utcnow()
        self.session.flush()
        return row
