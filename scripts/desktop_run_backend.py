#!/usr/bin/env python3
"""Windows desktop backend orchestrator — no PowerShell window/process."""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from desktop_stdio import configure_desktop_stdio, safe_print

configure_desktop_stdio()

from desktop_port_guard import (
    reclaim_backend_port,
    remove_pid_file,
    resolve_default_data_dir,
    write_pid_file,
)

from desktop_bundle_runtime import (
    find_portable_python_exe,
    portable_python_root,
    prepare_desktop_work_bundle,
    set_portable_python_env,
)


def log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_print(f"[backend] [{stamp}] {message}", flush=True)


def resolve_root() -> Path:
    if os.environ.get("HUOKE_ROOT"):
        return Path(os.environ["HUOKE_ROOT"]).resolve()
    return Path(__file__).resolve().parent.parent


def resolve_data_dir() -> Path:
    if os.environ.get("HUOKE_DATA_DIR"):
        return Path(os.environ["HUOKE_DATA_DIR"]).resolve()
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set")
    return Path(appdata) / "com.huoke.desktop"


def resolve_source_bundle(root: Path) -> Path:
    if os.environ.get("HUOKE_BUNDLE_DIR"):
        bundle = Path(os.environ["HUOKE_BUNDLE_DIR"]).resolve()
        if (bundle / "runtime").is_dir():
            return bundle
    for candidate in (root / "desktop" / "bundle", root / "bundle"):
        if (candidate / "runtime").is_dir():
            return candidate
    raise RuntimeError(f"bundle runtime not found under HUOKE_ROOT={root}")


def find_chrome() -> Path | None:
    local_app = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for candidate in (
        Path(program_files) / "Google/Chrome/Application/chrome.exe",
        Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
        Path(local_app) / "Google/Chrome/Application/chrome.exe",
    ):
        if candidate.is_file():
            return candidate
    return None


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ[name.strip()] = value.strip().strip('"')


def ensure_desktop_env_file(data_dir: Path, root: Path) -> Path:
    env_file = data_dir / ".env.desktop"
    if env_file.is_file():
        return env_file
    for candidate in (
        root / ".env.desktop.example",
        root / "resources" / ".env.desktop.example",
    ):
        if candidate.is_file():
            env_file.write_text(
                candidate.read_text(encoding="utf-8") + "\nANTIBOT_FINGERPRINT_PLATFORM=win\n",
                encoding="utf-8",
            )
            log(f"created desktop config: {env_file}")
            return env_file
    log("WARN: .env.desktop.example missing, using defaults")
    return env_file


def resolve_python(bundle_dir: Path, root: Path) -> tuple[Path, Path]:
    portable = find_portable_python_exe(bundle_dir)
    if portable is not None:
        return portable, bundle_dir / "backend"
    venv_python = bundle_dir / "runtime/.venv/Scripts/python.exe"
    if venv_python.is_file():
        return venv_python, bundle_dir / "backend"
    dev_venv = root / "backend/.venv/Scripts/python.exe"
    if dev_venv.is_file():
        return dev_venv, root / "backend"
    raise RuntimeError(f"Python runtime not found (bundle={bundle_dir})")


def maybe_reexec_with_work_python(work_python: Path) -> None:
    current = Path(sys.executable).resolve()
    target = work_python.resolve()
    if os.name == "nt" and current == target:
        return
    if os.name != "nt" and str(current) == str(target):
        return
    log(f"re-exec portable python: {target}")
    os.execv(str(target), [str(target), str(Path(__file__).resolve()), *sys.argv[1:]])


def setup_process_env(
    *,
    root: Path,
    bundle_dir: Path,
    data_dir: Path,
    backend_dir: Path,
    python_exe: Path,
    port: int,
    env_file: Path,
) -> None:
    storage_dir = data_dir / "storage"
    db_file = storage_dir / "huoke_desktop.db"
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "douyin/profile").mkdir(parents=True, exist_ok=True)

    os.environ["DESKTOP_MODE"] = "true"
    os.environ["HUOKE_BUNDLE_DIR"] = str(bundle_dir)
    os.environ["HUOKE_DATA_DIR"] = str(data_dir)
    os.environ["HUOKE_PYTHON_EXE"] = str(python_exe)
    backend_path = str(backend_dir)
    os.environ["PYTHONPATH"] = backend_path
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    os.environ["ANTIBOT_FINGERPRINT_PLATFORM"] = "win"
    os.environ["STORAGE_ROOT"] = str(storage_dir)
    os.environ["FRONTEND_ORIGIN"] = f"http://127.0.0.1:{port}"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_file.as_posix()}"
    os.environ["DOUYIN_PROFILE_DIR"] = str(storage_dir / "douyin/profile")

    frontend_dist = bundle_dir / "frontend-dist"
    index_file = frontend_dist / "index.html"
    if not index_file.is_file():
        raise RuntimeError(
            "桌面前端资源缺失，无法启动（frontend-dist/index.html）。"
            "请完全退出应用后重试；若仍失败，请删除 "
            f"{data_dir / 'runtime-work'} 后重新打开。"
        )
    os.environ["FRONTEND_DIST_DIR"] = str(frontend_dist)

    load_env_file(env_file)
    os.environ["DESKTOP_MODE"] = "true"
    os.environ["FRONTEND_ORIGIN"] = f"http://127.0.0.1:{port}"
    os.environ["ANTIBOT_FINGERPRINT_PLATFORM"] = "win"

    if find_portable_python_exe(bundle_dir) is not None:
        set_portable_python_env(python_exe)
        log(f"Python: {python_exe} (portable root={portable_python_root(python_exe)})")
    else:
        log(f"Python: {python_exe}")

    os.chdir(backend_dir)


def run_bootstrap(python_exe: Path, scripts_dir: Path) -> bool:
    python_root = portable_python_root(python_exe)
    bootstrap = python_root / "Lib/portable_dll_bootstrap.py"
    if not bootstrap.is_file():
        fallback = scripts_dir / "portable_dll_bootstrap.py"
        if fallback.is_file():
            bootstrap.parent.mkdir(parents=True, exist_ok=True)
            bootstrap.write_text(fallback.read_text(encoding="utf-8"), encoding="utf-8")
            log("installed portable_dll_bootstrap.py into runtime Lib")
    if not bootstrap.is_file():
        log("WARN: portable_dll_bootstrap.py missing")
        return False
    log("portable dll bootstrap")
    result = subprocess.run(
        [str(python_exe), str(bootstrap), "--heal-only"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0


def repair_native_runtime(python_exe: Path, bundle_dir: Path, scripts_dir: Path) -> bool:
    layout_ok = run_bootstrap(python_exe, scripts_dir)
    repair_wheels = bundle_dir / "runtime/repair-wheels"
    if not repair_wheels.is_dir():
        log(f"WARN: repair-wheels directory missing: {repair_wheels}")
        return layout_ok
    log(f"attempting offline native repair from {repair_wheels}")
    result = subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--find-links",
            str(repair_wheels),
            "--force-reinstall",
            "greenlet",
            "playwright",
            "cryptography",
            "pydantic-core",
        ],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return layout_ok or result.returncode == 0


def run_launcher(port: int, *, check_only: bool = False) -> int:
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import desktop_uvicorn_launcher as launcher

    argv = ["desktop_uvicorn_launcher.py", "--port", str(port)]
    if check_only:
        argv.append("--check-only")
    sys.argv = argv
    label = "unified preflight" if check_only else f"starting uvicorn on port {port}"
    log(label)
    return int(launcher.main())


def _prepare_runtime_bundle(source_bundle: Path, data_dir: Path, root: Path) -> tuple[Path, Path]:
    try:
        return prepare_desktop_work_bundle(source_bundle, data_dir, root)
    except OSError as exc:
        if getattr(exc, "errno", None) in {22, 28, 112}:
            raise RuntimeError(
                "无法准备运行时目录，可能是磁盘空间不足或安装路径不可写。"
                "请清理磁盘后重试，或卸载后重新安装到英文路径。"
            ) from exc
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("BACKEND_PORT", "18765")))
    args = parser.parse_args()

    try:
        log("desktop-run-backend starting")
        root = resolve_root()
        data_dir = resolve_data_dir()
        source_bundle = resolve_source_bundle(root)
        cached_bundle, work_bundle = _prepare_runtime_bundle(source_bundle, data_dir, root)
        log(
            f"root={root} sourceBundle={source_bundle} "
            f"cachedBundle={cached_bundle} workBundle={work_bundle}"
        )

        work_python = find_portable_python_exe(work_bundle)
        if work_python is not None:
            maybe_reexec_with_work_python(work_python)

        python_exe, backend_dir = resolve_python(work_bundle, root)
        if port_in_use(args.port):
            log(f"port {args.port} in use, attempting reclaim")
            killed = reclaim_backend_port(args.port, data_dir)
            if killed:
                log(f"reclaimed stale backend processes: {killed}")
            if port_in_use(args.port):
                raise RuntimeError(
                    f"port {args.port} is already in use by another application. "
                    "Close the other program or reboot and retry."
                )

        env_file = ensure_desktop_env_file(data_dir, root)
        write_pid_file(data_dir / "backend.pid", os.getpid())
        setup_process_env(
            root=root,
            bundle_dir=work_bundle,
            data_dir=data_dir,
            backend_dir=backend_dir,
            python_exe=python_exe,
            port=args.port,
            env_file=env_file,
        )

        chrome = find_chrome()
        if chrome is None:
            raise RuntimeError(
                "Google Chrome is required for browser automation. Install Chrome and restart the app."
            )
        log(f"Chrome: {chrome}")

        scripts_dir = Path(__file__).resolve().parent
        if find_portable_python_exe(work_bundle) is not None:
            run_bootstrap(python_exe, scripts_dir)

        code = run_launcher(args.port)
        if code == 0:
            return 0

        log(f"backend launcher failed (exit {code})")
        if repair_native_runtime(python_exe, work_bundle, scripts_dir):
            log("native repair completed; retrying launcher")
        if find_portable_python_exe(work_bundle) is not None:
            run_bootstrap(python_exe, scripts_dir)
        if run_launcher(args.port, check_only=True) != 0:
            raise RuntimeError("native repair completed but preflight still failed")
        return run_launcher(args.port)
    except Exception as exc:
        message = str(exc)
        try:
            remove_pid_file(resolve_default_data_dir() / "backend.pid")
        except Exception:
            pass
        if any(token in message.lower() for token in ("greenlet", "native", "dll", "vcruntime")):
            message += (
                "\n\nSuggestions: 1) Add install dir to antivirus allowlist "
                "2) Fully uninstall and reinstall "
                "3) If vcruntime is missing, install VC++ 2015-2022 x64: "
                "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            )
        log(f"FATAL: {message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
