#!/usr/bin/env python3
"""联调：主页 URL 视频采集（需本机抖音 Cookie 就绪）。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

TEST_URL = (
    "https://www.douyin.com/user/MS4wLjABAAAAI2P_yBUDrjJccqUniIzrnsKv-4wl9mtiUbeXApqenH5fWzgyo9hEBV6GqKzKV334"
    "?from_tab_name=main&vid=7617663855346404617"
)

os.environ.setdefault("STORAGE_ROOT", str(ROOT / "storage" / "dev"))
os.environ.setdefault("DOUYIN_HEADLESS", "true")


async def main() -> int:
    from app.core.config import get_settings
    from app.platforms.douyin.profile_videos import DouyinProfileVideosTool, parse_profile_input_url

    settings = get_settings()
    parsed = parse_profile_input_url(TEST_URL)
    print("=== parse_profile_input_url ===")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))

    tool = DouyinProfileVideosTool(settings, tenant_id="default", account_id="default")
    print("\n=== collect_profile_videos (limit=5, headless) ===")
    payload, output = await tool.collect_profile_videos(
        TEST_URL,
        limit=5,
        show_browser=False,
        days=None,
    )
    print(json.dumps(
        {
            "video_count": payload.get("video_count"),
            "capture_method": payload.get("capture_method"),
            "diagnostic": payload.get("diagnostic"),
            "sec_uid": payload.get("sec_uid"),
            "priority_vid": payload.get("priority_vid"),
            "videos": payload.get("videos"),
            "output_file": str(output),
        },
        ensure_ascii=False,
        indent=2,
    ))
    ok = bool(payload.get("videos"))
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
