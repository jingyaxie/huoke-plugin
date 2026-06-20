from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings

DEFAULT_INTENT_PATTERNS: list[str] = [
    r"多少钱|什么价|价格|报价|几块|一平|造价|费用",
    r"怎么买|想买|订购|下单|预约|订做|定制|有需要",
    r"哪里买|本地|安装|上门|师傅|同城|辽宁|沈阳|大连|抚顺|长春",
    r"联系|微信|电话|私信|vx|V信|加我|留个",
    r"感兴趣|想了解|考虑一下|怎么联系|能上门",
]

_COMMENT_FILE_RE = re.compile(
    r"^comments_(?P<platform>[a-z]+)_(?P<tenant>[^_]+)_(?P<aweme_id>\d+)_\d{8}_\d{6}\.json$",
    re.IGNORECASE,
)


def _safe_comment_path(settings: Settings, file_ref: str) -> Path | None:
    ref = (file_ref or "").strip()
    if not ref:
        return None
    base = settings.report_output_dir.resolve()
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = base / Path(ref).name
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_file():
        return None
    if base not in resolved.parents and resolved != base:
        return None
    if not _COMMENT_FILE_RE.match(resolved.name) and not resolved.name.startswith("comments_"):
        return None
    return resolved


def list_comment_files(
    settings: Settings,
    *,
    tenant_id: str,
    platform: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    root = settings.report_output_dir
    if not root.exists():
        return []
    pattern = f"comments_{platform}_{tenant_id}_*.json"
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    items: list[dict[str, Any]] = []
    for path in files[:limit]:
        match = _COMMENT_FILE_RE.match(path.name)
        aweme_id = match.group("aweme_id") if match else None
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        file_aweme: str | None = None
        total: int | None = None
        video_url: str | None = None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            total = int(data.get("total_comments_captured") or len(data.get("comments") or []))
            video_url = data.get("video_url") or data.get("note_url")
            file_aweme = data.get("aweme_id")
        except Exception:
            pass
        items.append(
            {
                "file_name": path.name,
                "path": str(path),
                "aweme_id": aweme_id or file_aweme,
                "video_url": video_url,
                "total_comments_captured": total,
                "modified_at": mtime.isoformat(timespec="seconds"),
            }
        )
    return items


def collect_comment_files_from_history(
    history: list[dict[str, Any]],
    settings: Settings,
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for msg in history:
        if msg.get("role") != "tool":
            continue
        raw = msg.get("content") or ""
        if not isinstance(raw, str) or not raw.strip().startswith("{"):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        refs: list[str] = []
        if data.get("output_file"):
            refs.append(str(data["output_file"]))
        refs.extend(str(p) for p in (data.get("output_files") or []))
        for ref in refs:
            path = _safe_comment_path(settings, ref)
            if path is None:
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(key)
    return paths


def _comment_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("comments")
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict)]
    return []


def _nickname(row: dict[str, Any]) -> str:
    for key in ("nickname", "user_name", "username", "nick_name"):
        val = row.get(key)
        if val:
            return str(val).strip()
    user = row.get("user")
    if isinstance(user, dict):
        for key in ("nickname", "unique_id", "uid"):
            if user.get(key):
                return str(user[key]).strip()
    return "未知用户"


def _matches_intent(text: str, patterns: list[str]) -> bool:
    if not text.strip():
        return False
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def read_comment_file(
    settings: Settings,
    file_ref: str,
    *,
    max_comments: int = 200,
    preview_only: bool = False,
) -> dict[str, Any]:
    path = _safe_comment_path(settings, file_ref)
    if path is None:
        return {"error": f"评论文件不存在或不可访问: {file_ref}"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"读取失败: {exc}"}
    rows = _comment_rows(payload)
    total = len(rows)
    if preview_only or total > max_comments:
        sample = rows[:max_comments]
        return {
            "file_name": path.name,
            "path": str(path),
            "aweme_id": payload.get("aweme_id"),
            "video_url": payload.get("video_url") or payload.get("note_url"),
            "keyword": (payload.get("keyword_context") or {}).get("keyword"),
            "total_comments_in_file": total,
            "returned_count": len(sample),
            "truncated": total > len(sample),
            "comments": sample,
            "hint": "完整数据在本地 JSON；分析意向用户请用 analyze_local_comments",
        }
    return {
        "file_name": path.name,
        "path": str(path),
        "aweme_id": payload.get("aweme_id"),
        "video_url": payload.get("video_url") or payload.get("note_url"),
        "total_comments_in_file": total,
        "comments": rows,
    }


def analyze_comment_leads(
    settings: Settings,
    *,
    file_refs: list[str] | None = None,
    tenant_id: str,
    platform: str,
    intent_keywords: list[str] | None = None,
    max_leads: int = 80,
) -> dict[str, Any]:
    patterns = list(DEFAULT_INTENT_PATTERNS)
    if intent_keywords:
        patterns.extend(re.escape(k) for k in intent_keywords if k.strip())

    resolved_paths: list[Path] = []
    if file_refs:
        for ref in file_refs:
            path = _safe_comment_path(settings, ref)
            if path is not None:
                resolved_paths.append(path)
    if not resolved_paths:
        for item in list_comment_files(settings, tenant_id=tenant_id, platform=platform, limit=10):
            path = _safe_comment_path(settings, item["file_name"])
            if path is not None:
                resolved_paths.append(path)

    if not resolved_paths:
        return {
            "error": "未找到可分析的本地评论文件。请先抓取评论（会生成 comments_*.json），或传入 file_names。",
            "hint": "用 list_local_comment_files 查看已下载文件",
        }

    leads: list[dict[str, Any]] = []
    files_summary: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for path in resolved_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = _comment_rows(payload)
        video_url = payload.get("video_url") or payload.get("note_url")
        aweme_id = payload.get("aweme_id")
        file_hits = 0
        for row in rows:
            text = str(row.get("comment") or row.get("text") or "").strip()
            if not _matches_intent(text, patterns):
                continue
            nick = _nickname(row)
            key = f"{nick}:{text[:80]}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            file_hits += 1
            leads.append(
                {
                    "nickname": nick,
                    "comment": text,
                    "aweme_id": aweme_id,
                    "video_url": video_url,
                    "source_file": path.name,
                    "digg_count": row.get("digg_count"),
                    "create_time": row.get("create_time"),
                    "comment_id": row.get("comment_id"),
                }
            )
            if len(leads) >= max_leads:
                break
        files_summary.append(
            {
                "file_name": path.name,
                "video_url": video_url,
                "total_comments": len(rows),
                "leads_in_file": file_hits,
            }
        )
        if len(leads) >= max_leads:
            break

    return {
        "status": "completed",
        "files_analyzed": len(files_summary),
        "files": files_summary,
        "lead_count": len(leads),
        "leads": leads,
        "intent_patterns_used": patterns[:10],
        "hint": "数据来自本地已下载 JSON，未重新抓取网页",
    }
