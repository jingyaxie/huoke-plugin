from __future__ import annotations

import io
import json
import os
import platform
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings

CORE_BUNDLE_RELATIVE_PATHS: tuple[str, ...] = (
    "runtime/python/python.exe",
    "backend/app/main.py",
    "backend/storage/skills/global.json",
    "frontend-dist/index.html",
)


def resolve_desktop_data_dir(settings: Settings) -> Path:
    env_dir = os.environ.get("HUOKE_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return settings.storage_root.parent.resolve()


def collect_bundle_integrity_issues(bundle_dir: Path) -> list[str]:
    issues: list[str] = []
    if not bundle_dir.is_dir():
        return [f"directory missing: {bundle_dir}"]
    for rel in CORE_BUNDLE_RELATIVE_PATHS:
        path = bundle_dir / rel.replace("/", os.sep)
        if not path.is_file():
            issues.append(f"missing: {rel}")
    backend_root = bundle_dir / "backend"
    if backend_root.is_dir():
        backend_files = sum(1 for item in backend_root.rglob("*") if item.is_file())
        if backend_files < 10:
            issues.append(f"backend incomplete: only {backend_files} file(s)")
    return issues


def _dir_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path)}
    if path.is_file():
        stat = path.stat()
        return {
            "exists": True,
            "path": str(path),
            "type": "file",
            "size": stat.st_size,
        }
    file_count = sum(1 for item in path.rglob("*") if item.is_file())
    return {
        "exists": True,
        "path": str(path),
        "type": "directory",
        "file_count": file_count,
    }


def _read_log_tail(path: Path, *, max_lines: int = 200, max_bytes: int = 256_000) -> str:
    if not path.is_file():
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)


def _discover_log_files(data_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    env_log = os.environ.get("HUOKE_LOG_FILE", "").strip()
    if env_log:
        candidates.append(Path(env_log).expanduser())
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "com.huoke.desktop" / "logs" / "AI获客平台.log"
        )
    candidates.append(data_dir / "logs" / "backend.log")
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _skill_registry_summary(settings: Settings) -> dict[str, Any]:
    skills_path = settings.storage_root / "skills" / "global.json"
    summary: dict[str, Any] = _dir_snapshot(skills_path)
    if not skills_path.is_file():
        return summary
    try:
        payload = json.loads(skills_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        summary["parse_error"] = str(exc)
        return summary
    skills = payload.get("skills") if isinstance(payload, dict) else None
    if isinstance(skills, list):
        enabled = [item for item in skills if isinstance(item, dict) and item.get("enabled", True)]
        summary["skill_count"] = len(skills)
        summary["enabled_skill_count"] = len(enabled)
        summary["enabled_skill_ids"] = [
            str(item.get("id", ""))
            for item in enabled
            if item.get("id")
        ]
    return summary


def repair_desktop_runtime(settings: Settings) -> dict[str, Any]:
    data_dir = resolve_desktop_data_dir(settings)
    cleared: list[str] = []
    for name in ("runtime-work", "bundle-cache"):
        target = data_dir / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            cleared.append(str(target))
    return {
        "message": "已清除运行时缓存，应用将重新解压安装包。账号与 Skill 配置未改动。",
        "cleared": cleared,
        "data_dir": str(data_dir),
        "need_restart": True,
    }


def build_desktop_diagnostics(settings: Settings) -> dict[str, Any]:
    data_dir = resolve_desktop_data_dir(settings)
    bundle_dir_env = os.environ.get("HUOKE_BUNDLE_DIR", "").strip()
    install_bundle = Path(bundle_dir_env).expanduser().resolve() if bundle_dir_env else None
    runtime_work = data_dir / "runtime-work" / "current"
    bundle_cache = data_dir / "bundle-cache" / "current"
    index_file = settings.frontend_dist_dir / "index.html"

    diagnostics: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "app_name": settings.app_name,
        "desktop_mode": settings.desktop_mode,
        "desktop_port": settings.desktop_port,
        "paths": {
            "data_dir": str(data_dir),
            "storage_root": str(settings.storage_root),
            "frontend_dist_dir": str(settings.frontend_dist_dir),
            "frontend_index_exists": index_file.is_file(),
            "install_bundle_dir": str(install_bundle) if install_bundle else None,
            "runtime_work_dir": str(runtime_work),
            "bundle_cache_dir": str(bundle_cache),
        },
        "directories": {
            "runtime_work": _dir_snapshot(runtime_work),
            "bundle_cache": _dir_snapshot(bundle_cache),
            "install_bundle": _dir_snapshot(install_bundle) if install_bundle else {"exists": False},
            "storage": _dir_snapshot(settings.storage_root),
        },
        "integrity_issues": {
            "runtime_work": collect_bundle_integrity_issues(runtime_work),
            "bundle_cache": collect_bundle_integrity_issues(bundle_cache),
            "install_bundle": collect_bundle_integrity_issues(install_bundle)
            if install_bundle and install_bundle.is_dir()
            else ["install bundle dir missing"],
        },
        "skills": _skill_registry_summary(settings),
        "environment": {
            "HUOKE_DATA_DIR": os.environ.get("HUOKE_DATA_DIR"),
            "HUOKE_BUNDLE_DIR": os.environ.get("HUOKE_BUNDLE_DIR"),
            "HUOKE_LOG_FILE": os.environ.get("HUOKE_LOG_FILE"),
            "DESKTOP_MODE": os.environ.get("DESKTOP_MODE"),
        },
        "logs": {},
    }

    for log_path in _discover_log_files(data_dir):
        tail = _read_log_tail(log_path)
        if tail:
            diagnostics["logs"][str(log_path)] = tail

    return diagnostics


def export_desktop_diagnostics_zip(settings: Settings) -> tuple[bytes, str]:
    payload = build_desktop_diagnostics(settings)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive_name = f"huoke-diagnostics-{timestamp}.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        for path_text, tail in payload.get("logs", {}).items():
            safe_name = Path(path_text).name or "log.txt"
            archive.writestr(f"logs/{safe_name}", tail)
    return buffer.getvalue(), archive_name
