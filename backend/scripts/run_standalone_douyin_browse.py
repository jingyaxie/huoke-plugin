#!/usr/bin/env python3

"""运行独立抖音关键词浏览流程（不经过 skill / 智能体）。



示例：

  python scripts/run_standalone_douyin_browse.py

  python scripts/run_standalone_douyin_browse.py --keyword AI获客 --target-leads 3



连续浏览多个视频，直到凑够目标条数精准线索；命中后测试回复/关注/私信并入库。

"""

from __future__ import annotations



import argparse

import asyncio

import json

import os

import sys

from pathlib import Path

from typing import Any



ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:

    sys.path.insert(0, str(ROOT))



from app.core.config import get_settings

from app.db.bootstrap import ensure_database_schema

from app.db.session import SessionLocal

from app.platforms.douyin.standalone_keyword_browse import (

    StandaloneKeywordBrowseConfig,

    run_standalone_keyword_browse_with_browser,

)





def _ensure_system_chrome_env() -> None:

    """仅使用本机 Google Chrome + storage_state，不用内置 Playwright Chromium。"""

    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

    os.environ.setdefault("ANTIBOT_BROWSER_CHANNEL", "chrome")

    os.environ.setdefault("DESKTOP_MODE", "true")

    appdata = os.environ.get("APPDATA", "")

    desktop_storage = Path(appdata) / "com.huoke.desktop" / "storage"

    if not os.environ.get("STORAGE_ROOT") and desktop_storage.is_dir():

        os.environ["STORAGE_ROOT"] = str(desktop_storage)





DEFAULT_KEYWORD = "AI获客"

DEFAULT_TARGET_LEADS = 3

DEFAULT_REPLY = "同意"

DEFAULT_DM = "hi"

DEFAULT_DESKTOP_PORT = 18765





def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="独立抖音浏览（关键词 / 单视频 / 主页）")
    parser.add_argument(
        "--mode",
        choices=["keyword", "video", "profile"],
        default="keyword",
        help="获客模式：keyword=关键词搜索，video=单视频，profile=账号主页",
    )
    parser.add_argument("--keyword", default=DEFAULT_KEYWORD, help=f"搜索关键词（默认 {DEFAULT_KEYWORD}）")
    parser.add_argument("--video-url", default="", help="单视频链接（--mode video）")
    parser.add_argument("--profile-url", default="", help="账号主页链接（--mode profile）")
    parser.add_argument("--days", type=int, default=7, help="视频发布时间筛选（天）")

    parser.add_argument("--comment-days", type=int, default=None, help="评论时间窗口（天），默认与 --days 相同")

    parser.add_argument("--target-leads", type=int, default=DEFAULT_TARGET_LEADS, help="目标精准线索条数")

    parser.add_argument("--max-videos", type=int, default=50, help="最多浏览视频数（安全上限）")

    parser.add_argument("--limit", type=int, default=None, help="已废弃，请用 --target-leads")

    parser.add_argument("--tenant", default="default", help="租户 ID")

    parser.add_argument("--account", default="default", help="账号 ID")

    parser.add_argument("--headless", action="store_true", help="无头模式")

    parser.add_argument(

        "--reuse-desktop",

        action=argparse.BooleanOptionalAction,

        default=False,

        help="调用 Huoke 桌面后端（需重启桌面加载新 API）；默认本地跑完整触达测试",

    )

    parser.add_argument("--desktop-port", type=int, default=DEFAULT_DESKTOP_PORT, help="桌面后端端口")

    parser.add_argument("--match-keywords", default="", help="评论匹配关键词，逗号分隔；留空则用搜索词+获客")

    parser.add_argument("--exclude-keywords", default="", help="排除关键词，逗号分隔")

    parser.add_argument(

        "--no-outreach",

        action="store_true",

        help="禁用触达（默认开启：回复+关注+私信）",

    )

    parser.add_argument("--reply-text", default=DEFAULT_REPLY, help=f"回复文案（默认 {DEFAULT_REPLY}）")

    parser.add_argument("--dm-text", default=DEFAULT_DM, help=f"私信文案（默认 {DEFAULT_DM}）")

    parser.add_argument("--no-persist", action="store_true", help="禁用精准线索入库")

    return parser.parse_args()





def _build_config(args: argparse.Namespace) -> StandaloneKeywordBrowseConfig:
    from app.platforms.douyin.standalone_keyword_browse import build_standalone_browse_config

    match_keywords = [k.strip() for k in args.match_keywords.split(",") if k.strip()]
    if not match_keywords and args.mode == "keyword":
        match_keywords = [args.keyword.strip(), "获客", "AI"]
    exclude_keywords = [k.strip() for k in args.exclude_keywords.split(",") if k.strip()]
    mode_map = {"keyword": "keyword_auto", "video": "single_video", "profile": "account_home"}
    return build_standalone_browse_config(
        acquisition_mode=mode_map.get(args.mode, "keyword_auto"),
        keyword=args.keyword.strip(),
        video_url=args.video_url.strip(),
        profile_url=args.profile_url.strip(),
        days=args.days,
        video_publish_days=args.days if args.mode == "profile" else None,
        comment_days=args.comment_days,
        target_precise_leads=max(1, int(args.target_leads or args.limit or DEFAULT_TARGET_LEADS)),
        limit=args.limit,
        max_videos_to_browse=int(args.max_videos),
        match_keywords=match_keywords,
        exclude_keywords=exclude_keywords,
        execute_outreach=not bool(args.no_outreach),
        test_all_outreach=not bool(args.no_outreach),
        reply_text=(args.reply_text or DEFAULT_REPLY).strip(),
        dm_text=(args.dm_text or DEFAULT_DM).strip(),
        persist_to_db=not bool(args.no_persist),
        close_browser_after=False,
    )





async def _desktop_health_ok(port: int) -> bool:

    try:

        import httpx

    except ImportError:

        return False

    try:

        async with httpx.AsyncClient(timeout=3.0) as client:

            resp = await client.get(f"http://127.0.0.1:{port}/api/health")

            return resp.status_code == 200

    except Exception:

        return False





async def _run_via_desktop_api(args: argparse.Namespace, config: StandaloneKeywordBrowseConfig) -> dict[str, Any] | None:

    if not args.reuse_desktop or args.headless:

        return None

    port = int(args.desktop_port)

    if not await _desktop_health_ok(port):

        return None



    try:

        import httpx

    except ImportError:

        print("[standalone] httpx 未安装，跳过桌面 API 复用", flush=True)

        return None



    payload = {

        "keyword": config.keyword,

        "days": config.days,

        "limit": config.content_limit,

        "target_precise_leads": config.target_precise_leads,

        "max_videos_to_browse": config.max_videos_to_browse,

        "comment_days": config.comment_days,

        "match_keywords": config.match_keywords,

        "exclude_keywords": config.exclude_keywords,

        "execute_outreach": config.execute_outreach,

        "test_all_outreach": config.test_all_outreach,

        "reply_text": config.reply_text,

        "dm_text": config.dm_text,

        "comment_ratio": config.action_policy.get("comment_ratio", 34),

        "dm_ratio": config.action_policy.get("dm_ratio", 33),

        "follow_ratio": config.action_policy.get("follow_ratio", 33),

        "persist_to_db": config.persist_to_db,

        "close_browser_after": False,

    }

    headers = {

        "X-Tenant-Id": args.tenant,

        "X-Account-Id": args.account,

        "X-Platform-Id": "douyin",

    }

    url = f"http://127.0.0.1:{port}/api/platforms/douyin/standalone/keyword-browse"

    print(f"[standalone] 复用桌面浏览器 via {url}", flush=True)

    async with httpx.AsyncClient(timeout=None) as client:

        resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code >= 400:

            print(f"[standalone] 桌面 API 失败 status={resp.status_code} body={resp.text[:500]}", flush=True)

            return None

        body = resp.json()

        data = body.get("data") or {}

        return {

            "ok": bool(body.get("ok")),

            "error": data.get("error"),

            "diagnostic": body.get("diagnostic"),

            "search_url": data.get("search_url"),

            "videos_processed": data.get("videos_processed"),

            "comments_scanned": data.get("comments_scanned"),

            "precise_lead_count": data.get("precise_lead_count"),

            "target_reached": data.get("target_reached"),

            "duplicates_skipped": data.get("duplicates_skipped"),

            "output_file": body.get("report_file"),

            "phase_log": data.get("phase_log") or [],

            "via": "desktop_api",

        }





async def _main() -> int:

    _ensure_system_chrome_env()

    ensure_database_schema()

    args = _parse_args()

    settings = get_settings()

    config = _build_config(args)



    print(

        f"[standalone] 关键词={config.keyword} 目标精准={config.target_precise_leads} "

        f"max_videos={config.max_videos_to_browse} days={config.days} "

        f"outreach={config.execute_outreach} reply={config.reply_text!r} dm={config.dm_text!r}",

        flush=True,

    )



    summary = await _run_via_desktop_api(args, config)

    if summary is None:

        db = SessionLocal()

        try:

            result = await run_standalone_keyword_browse_with_browser(

                settings,

                tenant_id=args.tenant,

                account_id=args.account,

                config=config,

                db_session=db if config.persist_to_db else None,

                headless=args.headless,

            )

            if config.persist_to_db:

                db.commit()

        except Exception:

            db.rollback()

            raise

        finally:

            db.close()

        summary = {

            "ok": result.ok,

            "error": result.error,

            "diagnostic": result.diagnostic,

            "search_url": result.search_url,

            "videos_processed": result.videos_processed,

            "comments_scanned": result.comments_scanned,

            "precise_lead_count": len(result.precise_leads),

            "target_reached": result.target_reached,

            "duplicates_skipped": result.duplicates_skipped,

            "output_file": result.output_file,

            "phase_log": result.phase_log[-20:],

            "via": "local_stable_session",

        }



    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    return 0 if summary.get("ok") else 1





if __name__ == "__main__":

    raise SystemExit(asyncio.run(_main()))

