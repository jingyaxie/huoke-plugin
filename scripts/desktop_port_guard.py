#!/usr/bin/env python3
"""Reclaim Huoke backend port from stale desktop/dev processes."""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKEND_MARKERS = (
    "app.main:app",
    "desktop_uvicorn_launcher",
    "desktop_run_backend",
    "desktop-run-backend",
    "uvicorn",
    "huoke",
)


def _log(message: str) -> None:
    print(f"[port-guard] {message}", flush=True)


def pid_file_path(data_dir: Path | None) -> Path | None:
    if data_dir is None:
        return None
    return data_dir / "backend.pid"


def read_pid_file(path: Path | None) -> int | None:
    if path is None or not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
        return int(value) if value else None
    except (OSError, ValueError):
        return None


def write_pid_file(path: Path | None, pid: int) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n", encoding="utf-8")
    except OSError:
        pass


def remove_pid_file(path: Path | None) -> None:
    if path is None or not path.is_file():
        return
    try:
        path.unlink()
    except OSError:
        pass


def process_command_line(pid: int) -> str:
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.returncode == 0:
                return (result.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def is_huoke_backend_process(pid: int, *, allow_pid_file: int | None = None) -> bool:
    if pid <= 0:
        return False
    if allow_pid_file is not None and pid == allow_pid_file:
        return True
    cmd = process_command_line(pid).lower()
    if not cmd:
        return False
    return any(marker in cmd for marker in BACKEND_MARKERS)


def listeners_on_port(port: int) -> list[int]:
    pids: list[int] = []
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.returncode != 0:
                return pids
            needle = f":{port}"
            for line in (result.stdout or "").splitlines():
                if "LISTENING" not in line.upper() or needle not in line:
                    continue
                parts = line.split()
                if not parts:
                    continue
                try:
                    pid = int(parts[-1])
                except ValueError:
                    continue
                if pid not in pids:
                    pids.append(pid)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return pids

    try:
        result = subprocess.run(
            ["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return pids
        for token in (result.stdout or "").split():
            try:
                pid = int(token.strip())
            except ValueError:
                continue
            if pid not in pids:
                pids.append(pid)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return pids


def terminate_process(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=8,
                check=False,
            )
            return result.returncode == 0
        return False
    except OSError:
        return False

    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            break
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=8,
                check=False,
            )
    return True


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def reclaim_backend_port(port: int, data_dir: Path | None = None) -> list[int]:
    pid_path = pid_file_path(data_dir)
    saved_pid = read_pid_file(pid_path)
    candidates: list[int] = []
    if saved_pid is not None:
        candidates.append(saved_pid)
    for pid in listeners_on_port(port):
        if pid not in candidates:
            candidates.append(pid)

    killed: list[int] = []
    for pid in candidates:
        if not is_huoke_backend_process(pid, allow_pid_file=saved_pid):
            continue
        _log(f"reclaim stale backend pid={pid} on port {port}")
        if terminate_process(pid):
            killed.append(pid)

    if killed:
        for _ in range(30):
            if not port_in_use(port):
                break
            time.sleep(0.1)

    if not port_in_use(port):
        remove_pid_file(pid_path)
    return killed


def resolve_default_data_dir() -> Path | None:
    if os.environ.get("HUOKE_DATA_DIR"):
        return Path(os.environ["HUOKE_DATA_DIR"]).resolve()
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "com.huoke.desktop"
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/com.huoke.desktop"
    return home / ".local/share/com.huoke.desktop"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclaim Huoke backend port")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--write-pid", action="store_true")
    parser.add_argument("--clear-pid", action="store_true")
    args = parser.parse_args()

    data_dir = args.data_dir or resolve_default_data_dir()
    pid_path = pid_file_path(data_dir)

    if args.clear_pid:
        remove_pid_file(pid_path)
        return 0

    if args.write_pid:
        write_pid_file(pid_path, os.getpid())
        return 0

    killed = reclaim_backend_port(args.port, data_dir)
    if killed:
        _log(f"reclaimed port {args.port}, killed={killed}")
    elif port_in_use(args.port):
        _log(f"port {args.port} still in use by non-Huoke process")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
