from __future__ import annotations

from typing import Any

from app.services.page_diagnosis.contracts import CrawlFailureSignal, Platform
from app.services.page_diagnosis.mappers.douyin import DouyinFailureMapper
from app.services.page_diagnosis.mappers.kuaishou import KuaishouFailureMapper
from app.services.page_diagnosis.mappers.xiaohongshu import XiaohongshuFailureMapper

PLATFORM_MAPPERS = {
    "douyin": DouyinFailureMapper(),
    "xiaohongshu": XiaohongshuFailureMapper(),
    "kuaishou": KuaishouFailureMapper(),
}


def normalize_platform(platform: str | None) -> Platform:
    value = str(platform or "douyin").strip().lower()
    if value in PLATFORM_MAPPERS:
        return value  # type: ignore[return-value]
    return "douyin"


def infer_implementation(skill_result: dict[str, Any] | None, *, has_page: bool) -> str:
    if isinstance(skill_result, dict):
        impl = str(skill_result.get("implementation") or skill_result.get("source") or "").strip().lower()
        if impl:
            return impl
        if skill_result.get("cache_replay"):
            return "cache"
        if skill_result.get("dry_run"):
            return "dry_run"
    if has_page:
        return "playwright"
    return "unknown"


def normalize_failure(
    *,
    platform: str | None,
    operation: str,
    implementation: str,
    skill_result: dict[str, Any] | None = None,
    exc: Exception | None = None,
) -> CrawlFailureSignal:
    plat = normalize_platform(platform)
    mapper = PLATFORM_MAPPERS[plat]
    if isinstance(skill_result, dict) and skill_result.get("failure_signal"):
        payload = dict(skill_result["failure_signal"])
        payload.setdefault("platform", plat)
        payload.setdefault("operation", operation)
        payload.setdefault("implementation", implementation)
        return CrawlFailureSignal.model_validate(payload)
    if exc is not None:
        return mapper.map_exception(exc, operation=operation, implementation=implementation)
    return mapper.map_skill_result(skill_result or {}, operation=operation, implementation=implementation)


async def probe_platform_page(platform: str | None, page) -> dict[str, Any]:
    plat = normalize_platform(platform)
    if plat == "douyin":
        from app.services.page_diagnosis.mappers.douyin import probe_douyin_page

        return await probe_douyin_page(page)
    if plat == "xiaohongshu":
        from app.services.page_diagnosis.mappers.xiaohongshu import probe_xiaohongshu_page

        return await probe_xiaohongshu_page(page)
    from app.services.page_diagnosis.mappers.kuaishou import probe_kuaishou_page

    return await probe_kuaishou_page(page)
