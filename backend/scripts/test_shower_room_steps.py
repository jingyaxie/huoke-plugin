#!/usr/bin/env python3
"""分步实测：搜索 → 抓评论 → 回复 → 关注 → 私信（抖音）。

--all：同一浏览器窗口，每步新开 Tab（首步可用主 Tab），步骤间停顿。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Awaitable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.platforms.douyin.comments import DouyinCommentCrawler
from app.platforms.douyin.js_constants import _extract_aweme_id
from app.platforms.douyin.session import DouyinSessionStore
from app.services.comment_reply_service import CommentReplyService
from app.services.playwright_pool import PlaywrightPool, TenantWindowSession
from app.services.supervisor_outreach import persist_crawl_skill_result

DEFAULT_KEYWORD = "淋浴房"
DEFAULT_REPLY_TEXT = "同意"
DEFAULT_DM_TEXT = "hi"
DEFAULT_STEP_PAUSE_S = 25
TENANT_ID = "default"
ACCOUNT_ID = "default"
STATE_PATH = Path("storage/dev/test_shower_room_state.json")


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_comment_user(payload: dict) -> dict | None:
    for row in payload.get("comments") or []:
        if not isinstance(row, dict):
            continue
        sec_uid = str(row.get("sec_uid") or "").strip()
        user_id = str(row.get("user_id") or "").strip()
        comment_id = str(row.get("comment_id") or "").strip()
        if sec_uid and user_id and comment_id:
            return {
                "comment_id": comment_id,
                "user_id": user_id,
                "sec_uid": sec_uid,
                "username": str(row.get("username") or row.get("nickname") or "").strip(),
                "comment_text": str(row.get("comment") or row.get("text") or "").strip(),
            }
    return None


async def _pause_between_steps(seconds: float, *, label: str) -> None:
    jitter = random.uniform(0.85, 1.15)
    wait_s = max(5.0, seconds * jitter)
    print(f"\n[节奏] {label}，停顿 {wait_s:.0f}s（模拟真人，勿频繁开关浏览器）\n", flush=True)
    await asyncio.sleep(wait_s)


async def step_search(
    state: dict,
    *,
    timeout_s: int,
    keyword: str,
    page,
    crawler: DouyinCommentCrawler,
) -> dict:
    report: dict = {"step": 1, "name": "search", "keyword": keyword, "ok": False}
    t0 = time.time()
    try:
        captured: list[str] = []

        def on_response(resp) -> None:
            if "/aweme/v1/web/" in resp.url:
                captured.append(resp.url)

        page.on("response", on_response)
        urls, diagnostic, template = await asyncio.wait_for(
            crawler._search.keyword_search(
                page,
                keyword=keyword,
                limit=3,
                captured_api_urls=captured,
                headless=False,
                manual_search=False,
                ui_search_only=True,
            ),
            timeout=timeout_s,
        )
        page.remove_listener("response", on_response)
        report.update(
            {
                "elapsed_s": round(time.time() - t0, 2),
                "diagnostic": diagnostic,
                "video_urls": urls,
                "template_preview": (template or "")[:160],
                "captured_apis": len(captured),
                "page_url": page.url,
                "ok": bool(urls),
            }
        )
        if urls:
            state["keyword"] = keyword
            state["video_url"] = urls[0]
            state["aweme_id"] = _extract_aweme_id(urls[0])
            state["search_template"] = template
            _save_state(state)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    return report


async def step_crawl_comments(
    state: dict,
    *,
    timeout_s: int,
    keyword: str,
    page,
    crawler: DouyinCommentCrawler,
    db,
) -> dict:
    video_url = str(state.get("video_url") or "").strip()
    aweme_id = str(state.get("aweme_id") or "").strip()
    if not video_url or not aweme_id:
        return {"step": 2, "name": "crawl_comments", "ok": False, "error": "缺少 step1 状态，请先跑 --step 1"}

    settings = crawler.settings
    report: dict = {"step": 2, "name": "crawl_comments", "video_url": video_url, "ok": False}
    t0 = time.time()
    try:
        payload, _output = await asyncio.wait_for(
            crawler._comments.crawl_video_comments(
                video_url,
                show_browser=True,
                page=page,
                max_comments=30,
            ),
            timeout=timeout_s,
        )
        payload["platform"] = "douyin"
        payload["keyword_context"] = {"keyword": keyword}
        persisted = persist_crawl_skill_result(
            db,
            settings,
            tenant_id=TENANT_ID,
            platform="douyin",
            skill_result={
                "results": [payload],
                "total_comments_captured": payload.get("total_comments_captured", 0),
            },
            source_keyword=keyword,
        )
        db.commit()
        target = _pick_comment_user(payload)
        report.update(
            {
                "elapsed_s": round(time.time() - t0, 2),
                "capture_method": payload.get("capture_method"),
                "total_comments_captured": payload.get("total_comments_captured"),
                "persisted_rows": persisted,
                "ok": bool(target),
            }
        )
        if target:
            state.update(
                {
                    "comment_id": target["comment_id"],
                    "user_id": target["user_id"],
                    "sec_uid": target["sec_uid"],
                    "username": target["username"],
                    "target_comment_text": target["comment_text"],
                }
            )
            _save_state(state)
            report["target_user"] = target
        else:
            report["error"] = "未找到含 sec_uid/user_id 的评论，无法继续触达测试"
    except Exception as exc:
        db.rollback()
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    return report


async def step_reply(
    state: dict,
    *,
    timeout_s: int,
    reply_text: str,
    page,
    settings: Settings,
    db,
) -> dict:
    comment_id = str(state.get("comment_id") or "").strip()
    if not comment_id:
        return {"step": 3, "name": "reply_comment", "ok": False, "error": "缺少 comment_id，请先跑 --step 2"}

    report: dict = {
        "step": 3,
        "name": "reply_comment",
        "comment_id": comment_id,
        "reply_text": reply_text,
        "ok": False,
    }
    t0 = time.time()
    try:
        service = CommentReplyService(
            settings,
            tenant_id=TENANT_ID,
            platform="douyin",
            session=db,
            account_id=ACCOUNT_ID,
        )
        result = await asyncio.wait_for(
            service.reply_comment(
                comment_id=comment_id,
                reply_text=reply_text,
                video_url=str(state.get("video_url") or "").strip() or None,
                comment_text=str(state.get("target_comment_text") or "").strip() or None,
                show_browser=True,
                warm_publish=True,
                page=page,
            ),
            timeout=timeout_s,
        )
        report.update(
            {
                "elapsed_s": round(time.time() - t0, 2),
                "status": result.get("status"),
                "capture_method": result.get("capture_method"),
                "content_url": result.get("content_url"),
                "error": result.get("error"),
                "ok": result.get("status") == "completed",
            }
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    return report


async def step_follow_and_dm(
    state: dict,
    *,
    timeout_s: int,
    dm_text: str,
    page,
    settings: Settings,
    do_follow: bool = True,
    do_dm: bool = True,
) -> dict:
    from app.services.social_roam.human.douyin.warm_outreach_profile import (
        warm_outreach_follow_dm_from_comment,
    )

    video_url = str(state.get("video_url") or "").strip()
    comment_id = str(state.get("comment_id") or "").strip()
    sec_uid = str(state.get("sec_uid") or "").strip()
    user_id = str(state.get("user_id") or "").strip()
    username = str(state.get("username") or "").strip()
    if not video_url or not sec_uid:
        return {
            "step": "4+5",
            "name": "follow_and_dm",
            "ok": False,
            "error": "缺少 video_url/sec_uid，请先跑 --step 2",
        }

    actions = []
    if do_follow:
        actions.append("follow")
    if do_dm:
        actions.append("dm")
    report: dict = {
        "step": "4+5" if do_follow and do_dm else (4 if do_follow else 5),
        "name": "+".join(actions) or "outreach",
        "sec_uid": sec_uid,
        "do_follow": do_follow,
        "do_dm": do_dm,
        "message": dm_text if do_dm else None,
        "ok": False,
    }
    t0 = time.time()
    try:
        result = await asyncio.wait_for(
            warm_outreach_follow_dm_from_comment(
                page,
                settings,
                tenant_id=TENANT_ID,
                account_id=ACCOUNT_ID,
                content_url=video_url,
                comment_id=comment_id,
                comment_text=str(state.get("target_comment_text") or ""),
                sec_uid=sec_uid,
                user_id=user_id,
                nickname=username,
                message=dm_text,
                do_follow=do_follow,
                do_dm=do_dm,
            ),
            timeout=timeout_s,
        )
        report.update(
            {
                "elapsed_s": round(time.time() - t0, 2),
                "result": result,
                "ok": bool(result.get("ok")),
                "error": result.get("error"),
            }
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["trace"] = traceback.format_exc()[-1500:]
    return report


async def _run_in_tab(
    win: TenantWindowSession,
    fn: Callable[..., Awaitable[dict]],
    *,
    state: dict,
    reuse_main: bool = False,
    close_after: bool = False,
    **kwargs: Any,
) -> dict:
    tab = await win.open_tab(reuse_main=reuse_main)
    try:
        return await fn(state, page=tab, **kwargs)
    finally:
        if close_after:
            await win.close_tab(tab)


async def _run_with_own_browser(
    fn: Callable[..., Awaitable[dict]],
    *,
    settings: Settings,
    store: DouyinSessionStore,
    kwargs: dict[str, Any],
) -> dict:
    """单步调试：开一个窗口、一个 Tab。"""
    pool = PlaywrightPool.get()
    db = kwargs.pop("db", None)
    own_db = db is None
    if own_db:
        db = SessionLocal()
    crawler = DouyinCommentCrawler(settings, TENANT_ID, store, account_id=ACCOUNT_ID)
    state = kwargs.pop("state", {})
    run_kwargs = {**kwargs, "settings": settings, "db": db}
    if fn in (step_search, step_crawl_comments):
        run_kwargs["crawler"] = crawler
    try:
        async with pool.tenant_window(
            "douyin", TENANT_ID, store, settings, headless=False, account_id=ACCOUNT_ID
        ) as win:
            return await _run_in_tab(
                win,
                fn,
                state=state,
                reuse_main=True,
                **run_kwargs,
            )
    finally:
        if own_db and db is not None:
            db.close()


async def _run_steps_in_one_session(
    *,
    settings: Settings,
    store: DouyinSessionStore,
    state: dict,
    keyword: str,
    reply_text: str,
    dm_text: str,
    timeout_s: int,
    pause_s: float,
    from_step: int = 1,
) -> tuple[int, list[dict]]:
    """同一浏览器窗口：from_step 起跑到结束（3=回复→关注→私信）。"""
    pool = PlaywrightPool.get()
    crawler = DouyinCommentCrawler(settings, TENANT_ID, store, account_id=ACCOUNT_ID)
    db = SessionLocal()
    summary: list[dict] = []
    exit_code = 0

    all_step_defs: tuple[tuple[str, Callable[..., Awaitable[dict]], dict[str, Any], bool], ...] = (
        ("搜索", step_search, {"keyword": keyword, "crawler": crawler}, True),
        ("抓评论", step_crawl_comments, {"keyword": keyword, "crawler": crawler, "db": db}, False),
        ("回复", step_reply, {"reply_text": reply_text, "settings": settings, "db": db}, False),
    )
    step_defs = [item for idx, item in enumerate(all_step_defs, start=1) if idx >= from_step]

    try:
        async with pool.tenant_window(
            "douyin", TENANT_ID, store, settings, headless=False, account_id=ACCOUNT_ID
        ) as win:
            print("[节奏] 复用同一浏览器窗口，每步新开 Tab，避免频繁开关窗口\n", flush=True)

            for label, fn, extra, reuse_main in step_defs:
                step_no = len(summary) + from_step
                print(f"\n{'='*60}\nSTEP {step_no}: {label}\n{'='*60}", flush=True)
                report = await _run_in_tab(
                    win,
                    fn,
                    state=state,
                    reuse_main=reuse_main,
                    timeout_s=timeout_s,
                    **extra,
                )
                summary.append(report)
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
                if not report.get("ok"):
                    return 1, summary
                await _pause_between_steps(pause_s, label=f"{label}完成后")

            if from_step <= 4:
                print(f"\n{'='*60}\nSTEP 4+5: 关注 + 私信（新 Tab，一次进主页）\n{'='*60}", flush=True)
                report = await _run_in_tab(
                    win,
                    step_follow_and_dm,
                    state=state,
                    timeout_s=timeout_s,
                    dm_text=dm_text,
                    settings=settings,
                    do_follow=True,
                    do_dm=True,
                )
                summary.append(report)
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
                if not report.get("ok"):
                    exit_code = 1
    finally:
        db.close()

    return exit_code, summary


async def _run_all_in_one_session(
    *,
    settings: Settings,
    store: DouyinSessionStore,
    state: dict,
    keyword: str,
    reply_text: str,
    dm_text: str,
    timeout_s: int,
    pause_s: float,
) -> tuple[int, list[dict]]:
    return await _run_steps_in_one_session(
        settings=settings,
        store=store,
        state=state,
        keyword=keyword,
        reply_text=reply_text,
        dm_text=dm_text,
        timeout_s=timeout_s,
        pause_s=pause_s,
        from_step=1,
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="抖音真实浏览器分步实测（搜索/抓评/回复/关注/私信）")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5], help="只跑指定步骤（会单独开浏览器）")
    parser.add_argument("--all", action="store_true", help="同一浏览器会话连续跑 1-5")
    parser.add_argument(
        "--from-step",
        type=int,
        choices=[1, 2, 3, 4],
        help="从第 N 步起在同一浏览器跑到结束（如 --from-step 3 = 回复→关注→私信）",
    )
    parser.add_argument("--keyword", default=DEFAULT_KEYWORD, help="搜索关键词")
    parser.add_argument("--reply-text", default=DEFAULT_REPLY_TEXT, help="回复评论文案")
    parser.add_argument("--dm-text", default=DEFAULT_DM_TEXT, help="私信文案")
    parser.add_argument("--timeout", type=int, default=180, help="单步超时秒数")
    parser.add_argument(
        "--pause-between-steps",
        type=float,
        default=DEFAULT_STEP_PAUSE_S,
        help=f"--all 时步骤间停顿秒数（默认 {DEFAULT_STEP_PAUSE_S}）",
    )
    args = parser.parse_args()

    if not args.step and not args.all and args.from_step is None:
        parser.error("请指定 --step N、--all 或 --from-step N")

    settings = get_settings()
    store = DouyinSessionStore(settings)
    login = store.login_status(TENANT_ID, account_id=ACCOUNT_ID)
    multi_step = args.all or args.from_step is not None
    print(
        json.dumps(
            {
                "storage_root": str(settings.storage_root),
                "login_status": login,
                "keyword": args.keyword,
                "reply_text": args.reply_text,
                "dm_text": args.dm_text,
                "from_step": args.from_step if args.from_step else (1 if args.all else None),
                "pause_between_steps": args.pause_between_steps if multi_step else None,
                "state": _load_state(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    if login.get("status") != "ready":
        print("登录态未就绪，请先在桌面 App 完成抖音账号绑定", file=sys.stderr)
        return 2

    state = _load_state()

    if args.all or args.from_step is not None:
        exit_code, _summary = await _run_steps_in_one_session(
            settings=settings,
            store=store,
            state=state,
            keyword=args.keyword,
            reply_text=args.reply_text,
            dm_text=args.dm_text,
            timeout_s=args.timeout,
            pause_s=args.pause_between_steps,
            from_step=args.from_step or 1,
        )
        print(f"\n状态文件: {STATE_PATH.resolve()}", flush=True)
        return exit_code

    # 单步：仍独立开浏览器，提醒勿连续快速跑多步
    print("\n[提示] 单步模式会单独开关浏览器；连续测多步请用 --all\n", flush=True)
    step_map = {
        1: ("搜索", step_search, {"keyword": args.keyword}),
        2: ("抓评论", step_crawl_comments, {"keyword": args.keyword}),
        3: ("回复评论", step_reply, {"reply_text": args.reply_text}),
        4: ("关注", step_follow_and_dm, {"dm_text": args.dm_text, "do_follow": True, "do_dm": False}),
        5: ("私信", step_follow_and_dm, {"dm_text": args.dm_text, "do_follow": False, "do_dm": True}),
    }
    label, fn, extra = step_map[args.step]
    print(f"\n{'='*60}\nSTEP {args.step}: {label}\n{'='*60}", flush=True)
    report = await _run_with_own_browser(
        fn,
        settings=settings,
        store=store,
        kwargs={**extra, "timeout_s": args.timeout, "state": state},
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"\n状态文件: {STATE_PATH.resolve()}", flush=True)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
