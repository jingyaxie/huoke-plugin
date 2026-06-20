from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


def normalize_region(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_days(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


@dataclass
class SearchFilterOptions:
    keyword: str
    region: str | None = None
    days: int | None = None

    def __post_init__(self) -> None:
        self.region = normalize_region(self.region)
        self.days = normalize_days(self.days)

    @classmethod
    def from_params(
        cls,
        *,
        keyword: str,
        region: str | None = None,
        days: int | None = None,
    ) -> SearchFilterOptions:
        return cls(keyword=keyword, region=region, days=days)

    @property
    def has_region(self) -> bool:
        return self.region is not None

    @property
    def has_days(self) -> bool:
        return self.days is not None and self.days > 0

    @property
    def active(self) -> bool:
        return self.has_region or self.has_days

    def composed_keyword(self) -> str:
        """方案1：地域拼入搜索词，提高召回。"""
        kw = (self.keyword or "").strip()
        region = (self.region or "").strip()
        if not region:
            return kw
        if region in kw:
            return kw
        return f"{region} {kw}"


def douyin_publish_time(days: int | None) -> str | None:
    """抖音 filter_selected.publish_time：1=一天, 7=一周, 180=半年。"""
    if not days or days <= 0:
        return None
    if days <= 1:
        return "1"
    if days <= 7:
        return "7"
    if days <= 180:
        return "180"
    return None


def douyin_publish_time_ui_label(days: int | None) -> str | None:
    """精选搜索页「发布时间」筛选项文案。"""
    code = douyin_publish_time(days)
    if code == "1":
        return "一天内"
    if code == "7":
        return "一周内"
    if code == "180":
        return "半年内"
    return None


def xhs_publish_time_ui_label(days: int | None) -> str | None:
    """小红书搜索页「发布时间」筛选项文案（与抖音精选页一致）。"""
    return douyin_publish_time_ui_label(days)


def douyin_filter_selected(days: int | None) -> dict | None:
    publish_time = douyin_publish_time(days)
    if not publish_time:
        return None
    return {"sort_type": "0", "publish_time": publish_time}


def douyin_filter_selected_json(days: int | None) -> str | None:
    selected = douyin_filter_selected(days)
    if not selected:
        return None
    return json.dumps(selected, separators=(",", ":"))


def fetch_multiplier(filters: SearchFilterOptions) -> int:
    if filters.has_region and filters.has_days:
        return 5
    if filters.has_region:
        return 4
    if filters.has_days:
        return 3
    return 1


def _region_tokens(region: str) -> list[str]:
    text = region.strip()
    if not text:
        return []
    tokens = [text]
    if text.endswith(("省", "市", "区", "县")):
        tokens.append(text[:-1])
    if "·" in text:
        tokens.extend(part.strip() for part in text.split("·") if part.strip())
    return list(dict.fromkeys(tokens))


def matches_region_text(text: str, region: str) -> bool:
    if not region.strip():
        return True
    haystack = (text or "").lower()
    for token in _region_tokens(region):
        if token.lower() in haystack:
            return True
    return False


def matches_region_item(item: dict, region: str | None, *, platform: str) -> bool:
    if not (region or "").strip():
        return True
    fields: list[str] = []
    if platform == "douyin":
        fields.extend(
            [
                item.get("ip_label") or "",
                item.get("poi_name") or "",
                item.get("poi_address") or "",
                item.get("title") or "",
                item.get("author") or "",
            ]
        )
    elif platform == "xiaohongshu":
        card = (item.get("raw_data") or {}).get("card") or item
        if isinstance(card, dict):
            tag = card.get("tag_info") or card.get("tagInfo") or {}
            if isinstance(tag, dict):
                fields.append(str(tag.get("title") or tag.get("name") or ""))
            fields.extend(
                [
                    card.get("desc") or "",
                    card.get("title") or "",
                    card.get("display_title") or "",
                    card.get("ip_location") or card.get("ipLocation") or "",
                ]
            )
        fields.extend(
            [
                item.get("title") or "",
                item.get("ip_location") or "",
            ]
        )
    elif platform == "kuaishou":
        feed = (item.get("raw_data") or {}).get("feed") or {}
        photo = feed.get("photo") or feed
        if isinstance(photo, dict):
            fields.extend(
                [
                    photo.get("caption") or "",
                    photo.get("location") or "",
                ]
            )
        fields.extend(
            [
                item.get("title") or "",
                item.get("author") or "",
                item.get("location") or "",
            ]
        )
    text = " ".join(str(f) for f in fields if f)
    return matches_region_text(text, region)


def within_days(create_time: Any, days: int | None) -> bool:
    if not days or days <= 0:
        return True
    if create_time is None:
        return True
    try:
        ts = int(create_time)
    except (TypeError, ValueError):
        return True
    if ts > 1_000_000_000_000:
        ts = ts // 1000
    cutoff = time.time() - days * 86400
    return ts >= cutoff


def filter_search_items(
    items: list[dict],
    *,
    region: str | None,
    days: int | None,
    platform: str,
    limit: int,
) -> tuple[list[dict], dict]:
    region = normalize_region(region)
    days = normalize_days(days)
    matched: list[dict] = []
    for item in items:
        if not matches_region_item(item, region, platform=platform):
            continue
        if not within_days(item.get("create_time"), days):
            continue
        matched.append(item)
        if len(matched) >= limit:
            break
    return matched, {
        "scanned": len(items),
        "matched": len(matched),
        "region": region,
        "days": days,
    }


def select_rows_after_filter(
    source: list[dict],
    filtered: list[dict],
    *,
    region: str | None,
    limit: int,
) -> list[dict]:
    """未传 region 时，时间筛选无命中则回退到原始排序结果。"""
    if filtered:
        return filtered[:limit]
    if not normalize_region(region):
        return source[:limit]
    return []


def filter_diagnostic_suffix(stats: dict, *, requested: int) -> str | None:
    region = normalize_region(stats.get("region"))
    days = normalize_days(stats.get("days"))
    if region is None and days is None:
        return None
    matched = stats.get("matched", 0)
    scanned = stats.get("scanned", 0)
    region_label = region or "-"
    days_label = days if days is not None else "-"
    if matched >= requested:
        return f"筛选后 {matched}/{scanned} 条命中（region={region_label}, days={days_label}）"
    return (
        f"筛选后仅 {matched}/{scanned} 条命中目标 {requested} 条"
        f"（region={region_label}, days={days_label}），可放宽条件或增大 limit"
    )
