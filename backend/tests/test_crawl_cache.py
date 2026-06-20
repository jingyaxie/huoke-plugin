from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.schemas.crawl_cache import CacheMeta
from app.services.crawl_cache_service import CrawlCacheService, build_cache_key, build_params_hash, normalize_cache_params
from app.services.comment_store_service import extract_content_id


def test_build_cache_key_stable():
    params = {"keyword": "淋浴房", "limit": 3, "days": 3, "region": None}
    key1 = build_cache_key("keyword_comments", "default", "douyin", "default", params)
    key2 = build_cache_key("keyword_comments", "default", "douyin", "default", params)
    assert key1 == key2
    assert key1.startswith("keyword_comments:default:douyin:default:")


def test_params_hash_ignores_none():
    h1 = build_params_hash({"keyword": "a", "region": None})
    h2 = build_params_hash({"keyword": "a"})
    assert h1 == h2


def test_extract_content_id_douyin():
    cid = extract_content_id(
        "douyin",
        "https://www.douyin.com/video/7622271232130910203",
        {},
    )
    assert cid == "7622271232130910203"


def test_cache_meta_defaults():
    meta = CacheMeta()
    assert meta.from_cache is False
    assert meta.cache_hit is False
    assert meta.stale_fallback is False
    assert meta.refresh_error is None


def test_lookup_stale_returns_expired_cache():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    settings = Settings()
    service = CrawlCacheService(session, settings, tenant_id="default", platform="douyin")
    params = {"keyword": "淋浴房", "limit": 3}
    service.store("search_videos", params, {"keyword": "淋浴房", "items": [{"id": "1"}]})
    session.commit()
    row = service.repo.get_by_key(build_cache_key("search_videos", "default", "douyin", "default", params))
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    session.commit()

    assert service.lookup("search_videos", params) is None
    stale = service.lookup_stale("search_videos", params)
    assert stale is not None
    assert stale.payload["items"] == [{"id": "1"}]
    assert stale.meta.from_cache is True
