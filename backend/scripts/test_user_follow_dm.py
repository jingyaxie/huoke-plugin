#!/usr/bin/env python3
"""测试：评论用户 → 主页 → 关注(JS) + 私信(轻量 UI)。"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.platforms.douyin.dm import DouyinDmTool
from app.platforms.douyin.follow import DouyinFollowTool
from app.platforms.douyin.profile import build_profile_url


def _load_user_from_report(report_path: Path, index: int = 0) -> dict:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    comments = data.get("comments") or []
    if not comments:
        raise ValueError(f"报告无评论: {report_path}")
    if index < 0 or index >= len(comments):
        raise IndexError(f"评论索引越界: {index}")
    row = comments[index]
    for key in ("sec_uid", "user_id"):
        if not row.get(key):
            raise ValueError(f"评论缺少 {key}: {row}")
    return row


async def main() -> int:
    report = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("reports/comments_douyin_default_7647471881613138597_20260610_215454.json")
    )
    index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    do_follow = "--no-follow" not in sys.argv
    do_dm = "--no-dm" not in sys.argv
    timeout_s = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 120

    user = _load_user_from_report(report, index)
    message = f"你好，测试私信 {datetime.now().strftime('%H:%M:%S')}"

    settings = get_settings()
    follow_tool = DouyinFollowTool(settings, "default")
    dm_tool = DouyinDmTool(settings, "default")
    report_out: dict = {
        "report": str(report),
        "user_index": index,
        "username": user.get("username"),
        "user_id": user.get("user_id"),
        "sec_uid": user.get("sec_uid"),
        "profile_url": build_profile_url(user["sec_uid"]),
        "follow": do_follow,
        "send_message": do_dm,
        "message": message if do_dm else None,
    }

    t0 = time.time()
    try:
        result: dict = {
            "username": user.get("username"),
            "user_id": user.get("user_id"),
            "sec_uid": user["sec_uid"],
            "profile_url": build_profile_url(user["sec_uid"]),
        }
        if do_follow:
            result["follow"] = await asyncio.wait_for(
                follow_tool.follow_user(
                    sec_uid=user["sec_uid"],
                    user_id=user["user_id"],
                    username=user.get("username") or "",
                ),
                timeout=timeout_s,
            )
        if do_dm:
            result["dm"] = await asyncio.wait_for(
                dm_tool.send_message(
                    sec_uid=user["sec_uid"],
                    message=message,
                    username=user.get("username") or "",
                ),
                timeout=timeout_s,
            )
        report_out.update(
            {
                "ok": True,
                "elapsed_s": round(time.time() - t0, 1),
                "result": result,
            }
        )
    except asyncio.TimeoutError:
        report_out.update({"ok": False, "error": f"timeout_{timeout_s}s", "elapsed_s": round(time.time() - t0, 1)})
    except Exception as exc:
        report_out.update(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - t0, 1),
                "trace": traceback.format_exc()[-1200:],
            }
        )

    print(json.dumps(report_out, ensure_ascii=False, indent=2))
    return 0 if report_out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
