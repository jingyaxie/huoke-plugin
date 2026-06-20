#!/usr/bin/env python3
"""真实浏览器一键实测：搜索接口 + 抓评/回复/关注/私信（抖音）。

默认：评论回复「同意」，私信「hi」。复用桌面 App 登录态。

用法:
  python scripts/test_real_browser_interfaces.py
  python scripts/test_real_browser_interfaces.py --skip-search-diag
  python scripts/test_real_browser_interfaces.py --outreach-only --step 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ensure_env() -> None:
    appdata = os.environ.get("APPDATA", "")
    desktop_storage = Path(appdata) / "com.huoke.desktop" / "storage"
    if not os.environ.get("STORAGE_ROOT") and desktop_storage.is_dir():
        os.environ["STORAGE_ROOT"] = str(desktop_storage)
    os.environ.setdefault("DESKTOP_MODE", "true")
    os.environ.setdefault("ANTIBOT_BROWSER_CHANNEL", "chrome")
    dev_db = ROOT / "storage" / "dev" / "real_browser_test.db"
    dev_db.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./storage/dev/real_browser_test.db")


def _print_json(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace") + b"\n")
        sys.stdout.flush()


async def _run_search_diag(keyword: str, python: str) -> dict:
    script = ROOT / "scripts" / "diag_douyin_search_methods.py"
    proc = await asyncio.create_subprocess_exec(
        python,
        str(script),
        keyword,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
        env=os.environ.copy(),
    )
    stdout, stderr = await proc.communicate()
    text = stdout.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {"raw_stdout": text, "stderr": stderr.decode("utf-8", errors="replace")}
    payload["exit_code"] = proc.returncode
    payload["phase"] = "search_interfaces"
    return payload


async def _run_outreach(args, python: str) -> dict:
    script = ROOT / "scripts" / "test_shower_room_steps.py"
    cmd = [
        python,
        str(script),
        "--keyword",
        args.keyword,
        "--reply-text",
        args.reply_text,
        "--dm-text",
        args.dm_text,
        "--timeout",
        str(args.timeout),
    ]
    if args.outreach_only and args.step:
        cmd.extend(["--step", str(args.step)])
    else:
        cmd.append("--all")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(ROOT),
        env=os.environ.copy(),
    )
    stdout, _ = await proc.communicate()
    text = stdout.decode("utf-8", errors="replace")
    return {
        "phase": "outreach_interfaces",
        "exit_code": proc.returncode,
        "log_tail": text[-12000:],
    }


async def main() -> int:
    _ensure_env()
    parser = argparse.ArgumentParser(description="抖音真实浏览器接口一键实测")
    parser.add_argument("--keyword", default="淋浴房")
    parser.add_argument("--reply-text", default="同意")
    parser.add_argument("--dm-text", default="hi")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--skip-search-diag", action="store_true")
    parser.add_argument("--outreach-only", action="store_true", help="只跑触达步骤（跳过搜索接口 diag）")
    parser.add_argument("--step", type=int, choices=[1, 2, 3, 4, 5])
    args = parser.parse_args()

    python = sys.executable
    report: dict = {
        "keyword": args.keyword,
        "reply_text": args.reply_text,
        "dm_text": args.dm_text,
        "storage_root": os.environ.get("STORAGE_ROOT"),
        "phases": [],
    }

    if not args.skip_search_diag and not args.outreach_only:
        print("=== Phase 1: search diag ===", flush=True)
        search_report = await _run_search_diag(args.keyword, python)
        report["phases"].append(search_report)
        _print_json(search_report)

    print("\n=== Phase 2: crawl/reply/follow/dm ===", flush=True)
    outreach_report = await _run_outreach(args, python)
    report["phases"].append(outreach_report)
    try:
        print(outreach_report.get("log_tail") or "", flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(
            (outreach_report.get("log_tail") or "").encode("utf-8", errors="replace") + b"\n"
        )
        sys.stdout.flush()

    out_path = ROOT / "storage" / "dev" / "real_browser_interfaces_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {out_path}", flush=True)

    codes = [p.get("exit_code", 0) for p in report["phases"]]
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
