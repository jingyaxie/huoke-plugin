"""Bundle cache + runtime-work sync for Windows desktop (Python, no PowerShell)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def path_has_non_ascii(path: str) -> bool:
    return any(ord(ch) > 127 for ch in path)


def find_portable_python_exe(bundle_dir: Path) -> Path | None:
    for rel in (
        "runtime/python/python.exe",
        "runtime/python/bin/python.exe",
        "runtime/python/bin/python3.exe",
        "runtime/python/bin/python3.12.exe",
    ):
        candidate = bundle_dir / rel
        if candidate.is_file():
            return candidate
    return None


def portable_python_root(python_exe: Path) -> Path:
    root = python_exe.parent
    if root.name == "bin":
        return root.parent
    return root


def set_portable_python_env(python_exe: Path) -> None:
    python_root = portable_python_root(python_exe)
    os.environ.pop("PYTHONHOME", None)
    os.environ["PYTHONUTF8"] = "1"
    runtime_root = python_root.parent
    dll_dirs = [
        python_root,
        python_root / "DLLs",
        runtime_root / "msvc",
    ]
    prefix = ";".join(str(p) for p in dll_dirs if p.is_dir())
    if prefix:
        os.environ["PATH"] = f"{prefix};{os.environ.get('PATH', '')}"


def probe_portable_python(python_exe: Path, backend_dir: Path) -> tuple[bool, str]:
    if not python_exe.is_file():
        return False, f"python exe missing: {python_exe}"
    if not backend_dir.is_dir():
        return False, f"backend dir missing: {backend_dir}"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir)
    set_portable_python_env(python_exe)
    env["PATH"] = os.environ.get("PATH", "")
    result = subprocess.run(
        [str(python_exe), "-c", "import uvicorn; print('portable python probe ok')"],
        capture_output=True,
        text=True,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()


def bundle_fingerprint(bundle_dir: Path) -> str:
    manifest = bundle_dir / "BUNDLE_MANIFEST.json"
    if manifest.is_file():
        return hashlib.sha256(manifest.read_bytes()).hexdigest()
    runtime_manifest = bundle_dir / "RUNTIME_MANIFEST.json"
    if runtime_manifest.is_file():
        return hashlib.sha256(runtime_manifest.read_bytes()).hexdigest()
    return str(int(bundle_dir.stat().st_mtime_ns))


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"copy source missing: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        dst = destination / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True, symlinks=True)
        else:
            shutil.copy2(item, dst, follow_symlinks=True)


def copy_bundle_components(source_bundle: Path, target_bundle: Path) -> None:
    for name in ("runtime", "backend", "frontend-dist"):
        src = source_bundle / name
        if src.exists():
            copy_tree(src, target_bundle / name)
    for name in ("BUNDLE_MANIFEST.json", "RUNTIME_MANIFEST.json"):
        src = source_bundle / name
        if src.is_file():
            shutil.copy2(src, target_bundle / name)


CORE_BUNDLE_RELATIVE_PATHS: tuple[str, ...] = (
    "runtime/python/python.exe",
    "backend/app/main.py",
    "backend/storage/skills/global.json",
    "frontend-dist/index.html",
)


def collect_bundle_integrity_issues(bundle_dir: Path) -> list[str]:
    """检查桌面 bundle 是否包含 API、前端、内置 Skill 与 Python 运行时。"""
    issues: list[str] = []
    for rel in CORE_BUNDLE_RELATIVE_PATHS:
        path = bundle_dir / rel.replace("/", os.sep)
        if not path.is_file():
            issues.append(f"missing: {rel}")
    backend_root = bundle_dir / "backend"
    if backend_root.is_dir():
        backend_files = sum(1 for _ in backend_root.rglob("*") if _.is_file())
        if backend_files < 10:
            issues.append(f"backend incomplete: only {backend_files} file(s)")
    return issues


def runtime_workdir_backend_ready(work_bundle: Path) -> bool:
    """runtime-work 必须包含可运行的 backend、前端与内置 Skill。"""
    return not collect_bundle_integrity_issues(work_bundle)


def clear_runtime_workdir(data_dir: Path) -> None:
    work_root = data_dir / "runtime-work"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)


def file_fingerprint(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def verify_runtime_manifest(bundle_dir: Path, *, strict: bool = False) -> tuple[bool, list[str]]:
    manifest_file = bundle_dir / "RUNTIME_MANIFEST.json"
    if not manifest_file.is_file():
        issues = ["RUNTIME_MANIFEST.json missing"]
        if strict:
            raise RuntimeError(issues[0])
        return False, issues
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    issues: list[str] = []
    for entry in data.get("files", []):
        rel = str(entry.get("relative", "")).replace("/", os.sep)
        full_path = bundle_dir / rel
        if not full_path.is_file():
            issues.append(f"missing: {entry.get('relative')}")
            continue
        fp = file_fingerprint(full_path)
        if int(entry.get("size", -1)) != int(fp["size"]):
            issues.append(f"size mismatch: {entry.get('relative')}")
        expected = str(entry.get("sha256", "")).upper()
        actual = str(fp["sha256"]).upper()
        if expected != actual:
            issues.append(f"hash mismatch: {entry.get('relative')}")
    ok = not issues
    if strict and not ok:
        raise RuntimeError("Runtime manifest verification failed:\n" + "\n".join(issues))
    return ok, issues


def clear_bundle_cache(data_dir: Path) -> None:
    cache_root = data_dir / "bundle-cache"
    if cache_root.exists():
        shutil.rmtree(cache_root, ignore_errors=True)


def sync_bundle_cache(source_bundle_dir: Path, data_dir: Path, root: Path) -> Path:
    if not (source_bundle_dir / "runtime").is_dir():
        raise RuntimeError(f"Source bundle missing runtime: {source_bundle_dir}")

    if not path_has_non_ascii(str(root)) and not path_has_non_ascii(str(source_bundle_dir)):
        issues = collect_bundle_integrity_issues(source_bundle_dir)
        if issues:
            raise RuntimeError(
                "安装包 runtime bundle 不完整: " + "; ".join(issues)
            )
        return source_bundle_dir

    python_exe = find_portable_python_exe(source_bundle_dir)
    if python_exe is None:
        raise RuntimeError(
            f"Unicode install path but portable Python not found under {source_bundle_dir}"
        )

    cache_root = data_dir / "bundle-cache"
    cache_bundle = cache_root / "current"
    manifest_file = cache_root / "CACHE_MANIFEST.json"
    fingerprint = bundle_fingerprint(source_bundle_dir)

    if manifest_file.is_file() and cache_bundle.is_dir():
        try:
            existing = json.loads(manifest_file.read_text(encoding="utf-8"))
            if existing.get("fingerprint") == fingerprint and (cache_bundle / "runtime").is_dir():
                cache_issues = collect_bundle_integrity_issues(cache_bundle)
                cached_python = find_portable_python_exe(cache_bundle)
                if not cache_issues and cached_python is not None:
                    ok, _ = probe_portable_python(cached_python, cache_bundle / "backend")
                    if ok:
                        print(f"Reusing bundle cache: {cache_bundle}", flush=True)
                        return cache_bundle
                if cache_issues:
                    print(
                        "WARN: bundle cache incomplete, resyncing: "
                        + "; ".join(cache_issues),
                        flush=True,
                    )
        except Exception:
            pass

    print(f"Syncing bundle cache to ASCII path: {cache_bundle}", flush=True)
    if cache_bundle.exists():
        shutil.rmtree(cache_bundle, ignore_errors=True)
    cache_bundle.mkdir(parents=True, exist_ok=True)
    copy_bundle_components(source_bundle_dir, cache_bundle)
    cache_issues = collect_bundle_integrity_issues(cache_bundle)
    if cache_issues:
        clear_bundle_cache(data_dir)
        raise RuntimeError(
            "Bundle cache sync completed but bundle is incomplete: "
            + "; ".join(cache_issues)
        )

    manifest_file.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "source": str(source_bundle_dir),
                "cached_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cached_python = find_portable_python_exe(cache_bundle)
    if cached_python is None:
        clear_bundle_cache(data_dir)
        raise RuntimeError("Bundle cache sync completed but portable Python is missing")
    ok, detail = probe_portable_python(cached_python, cache_bundle / "backend")
    if not ok:
        clear_bundle_cache(data_dir)
        raise RuntimeError(f"Bundle cache sync completed but portable Python probe failed: {detail}")
    return cache_bundle


def sync_runtime_workdir(source_bundle_dir: Path, data_dir: Path, *, force: bool = False) -> Path:
    if not (source_bundle_dir / "runtime").is_dir():
        raise RuntimeError(f"Source bundle missing runtime: {source_bundle_dir}")

    ok, issues = verify_runtime_manifest(source_bundle_dir, strict=False)
    if not ok:
        print(f"WARN: source bundle manifest issues: {'; '.join(issues)}", flush=True)

    work_root = data_dir / "runtime-work"
    work_bundle = work_root / "current"
    state_file = work_root / "WORK_STATE.json"
    fingerprint = bundle_fingerprint(source_bundle_dir)

    if not force and state_file.is_file() and (work_bundle / "runtime").is_dir():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("fingerprint") == fingerprint and runtime_workdir_backend_ready(work_bundle):
                work_ok, _ = verify_runtime_manifest(work_bundle, strict=False)
                if work_ok:
                    print(f"Reusing runtime-work: {work_bundle}", flush=True)
                    return work_bundle
        except Exception:
            pass

    print(f"Syncing runtime-work: {work_bundle}", flush=True)
    if work_bundle.exists():
        shutil.rmtree(work_bundle, ignore_errors=True)
    work_bundle.mkdir(parents=True, exist_ok=True)
    copy_bundle_components(source_bundle_dir, work_bundle)
    if not runtime_workdir_backend_ready(work_bundle):
        issues = collect_bundle_integrity_issues(work_bundle)
        raise RuntimeError(
            "runtime-work sync completed but bundle is incomplete: "
            + ("; ".join(issues) if issues else "unknown")
        )

    work_ok, work_issues = verify_runtime_manifest(work_bundle, strict=False)
    if not work_ok:
        missing_manifest_only = work_issues == ["RUNTIME_MANIFEST.json missing"]
        hash_only = work_issues and all(item.startswith("hash mismatch:") for item in work_issues)
        if missing_manifest_only:
            print("WARN: RUNTIME_MANIFEST.json missing in runtime-work; continuing", flush=True)
        elif hash_only:
            print("WARN: runtime-work hash metadata mismatch; continuing", flush=True)
        else:
            raise RuntimeError(
                "runtime-work sync completed but manifest verification failed: "
                + "; ".join(work_issues)
            )

    state_file.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "source": str(source_bundle_dir),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"runtime-work synced: {work_bundle}", flush=True)
    return work_bundle


def prepare_desktop_work_bundle(
    source_bundle_dir: Path,
    data_dir: Path,
    root: Path,
) -> tuple[Path, Path]:
    """同步 bundle-cache 与 runtime-work；发现残缺目录时自动清除并重试。"""
    source_issues = collect_bundle_integrity_issues(source_bundle_dir)
    if source_issues:
        raise RuntimeError(
            "安装包 runtime bundle 不完整，请重新安装应用: "
            + "; ".join(source_issues)
        )

    last_error: RuntimeError | None = None
    for attempt in range(3):
        if attempt == 1:
            print("desktop bundle self-heal: clearing runtime-work", flush=True)
            clear_runtime_workdir(data_dir)
        elif attempt == 2:
            print("desktop bundle self-heal: clearing bundle-cache and runtime-work", flush=True)
            clear_bundle_cache(data_dir)
            clear_runtime_workdir(data_dir)

        try:
            cached_bundle = sync_bundle_cache(source_bundle_dir, data_dir, root)
            cache_issues = collect_bundle_integrity_issues(cached_bundle)
            if cache_issues:
                raise RuntimeError(
                    "bundle cache incomplete: " + "; ".join(cache_issues)
                )

            force = attempt > 0
            work_bundle = sync_runtime_workdir(
                cached_bundle,
                data_dir,
                force=force,
            )
            work_issues = collect_bundle_integrity_issues(work_bundle)
            if work_issues:
                raise RuntimeError(
                    "runtime-work incomplete: " + "; ".join(work_issues)
                )
            return cached_bundle, work_bundle
        except RuntimeError as exc:
            last_error = exc
            print(f"WARN: desktop bundle prepare failed: {exc}", flush=True)

    raise RuntimeError(
        "无法准备桌面运行时目录（已尝试自动修复）。"
        "请完全退出应用后删除 "
        f"{data_dir / 'runtime-work'} 与 {data_dir / 'bundle-cache'} 再重试。"
        + (f" 最后错误: {last_error}" if last_error else "")
    )
