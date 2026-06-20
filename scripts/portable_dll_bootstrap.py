"""Register and preload MSVC/Python DLLs before native extension imports (Windows)."""
from __future__ import annotations

import glob
import os
import shutil
import sys


def _python_layout() -> tuple[str, str]:
    exe = os.path.abspath(sys.executable)
    base = os.path.dirname(exe)
    if os.path.basename(base) == "bin":
        base = os.path.dirname(base)
    runtime_root = os.path.dirname(base)
    return base, runtime_root


def _dll_search_dirs(base: str, runtime_root: str) -> list[str]:
    dirs = [
        base,
        os.path.join(base, "DLLs"),
        os.path.join(runtime_root, "msvc"),
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in dirs:
        norm = os.path.normcase(os.path.abspath(candidate))
        if norm in seen or not os.path.isdir(candidate):
            continue
        seen.add(norm)
        unique.append(candidate)
    return unique


def _find_runtime_dll(base: str, runtime_root: str, name: str) -> str | None:
    for directory in (base, os.path.join(base, "DLLs"), os.path.join(runtime_root, "msvc")):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return os.path.abspath(path)
    return None


def _collect_runtime_dlls(base: str, runtime_root: str) -> list[str]:
    names = ("python312.dll", "vcruntime140.dll", "vcruntime140_1.dll")
    found: list[str] = []
    for name in names:
        path = _find_runtime_dll(base, runtime_root, name)
        if path:
            found.append(path)
    return found


def _preload_dlls(paths: list[str]) -> None:
    if os.name != "nt" or not paths:
        return
    try:
        import ctypes
    except ImportError:
        return
    for path in paths:
        try:
            ctypes.WinDLL(path)
        except OSError:
            pass


_BOOTSTRAP_ENV = "HUOKE_DLL_BOOTSTRAP_DONE"


def _register_dll_directories(directories: list[str], base: str, runtime_root: str) -> None:
    if os.name != "nt":
        return
    for candidate in directories:
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(candidate)
            except OSError:
                pass
    if os.environ.get(_BOOTSTRAP_ENV) == "1":
        return
    path_prefix = [
        os.path.abspath(base),
        os.path.abspath(os.path.join(base, "DLLs")),
        os.path.abspath(os.path.join(runtime_root, "msvc")),
    ]
    path_prefix = [p for p in path_prefix if os.path.isdir(p)]
    if path_prefix:
        existing = os.environ.get("PATH", "")
        os.environ["PATH"] = ";".join(path_prefix + ([existing] if existing else []))
    os.environ[_BOOTSTRAP_ENV] = "1"


def _ensure_runtime_dlls_beside_pyds(base: str, runtime_root: str, runtime_dlls: list[str]) -> int:
    if os.name != "nt" or not runtime_dlls:
        return 0
    site_packages = os.path.join(base, "Lib", "site-packages")
    if not os.path.isdir(site_packages):
        return 0
    vc_only = [path for path in runtime_dlls if os.path.basename(path).lower().startswith("vcruntime")]
    if not vc_only:
        return 0
    copied = 0
    pyd_dirs = {os.path.dirname(pyd) for pyd in glob.glob(os.path.join(site_packages, "**", "*.pyd"), recursive=True)}
    for pkg_dir in pyd_dirs:
        for src in vc_only:
            dst = os.path.join(pkg_dir, os.path.basename(src))
            try:
                if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
                    continue
                shutil.copy2(src, dst)
                copied += 1
            except OSError:
                pass
    return copied


def bootstrap_portable_python_dlls(*, heal_layout: bool = False) -> dict[str, object]:
    if os.name != "nt":
        return {"ok": True, "platform": os.name}
    base, runtime_root = _python_layout()
    directories = _dll_search_dirs(base, runtime_root)
    runtime_dlls = _collect_runtime_dlls(base, runtime_root)
    _preload_dlls(runtime_dlls)
    _register_dll_directories(directories, base, runtime_root)
    copied = _ensure_runtime_dlls_beside_pyds(base, runtime_root, runtime_dlls) if heal_layout else 0
    return {
        "ok": True,
        "python_base": base,
        "runtime_root": runtime_root,
        "runtime_dlls": [os.path.basename(p) for p in runtime_dlls],
        "dll_dirs": len(directories),
        "vc_runtime_copies": copied,
    }


if __name__ == "__main__":
    import argparse

    _script_dir = os.path.dirname(os.path.abspath(__file__))
    if _script_dir not in sys.path:
        sys.path.insert(0, _script_dir)
    from desktop_stdio import configure_pipe_stdio, log_line

    configure_pipe_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--heal-only", action="store_true", help="Copy/preload DLLs without failing the process")
    args = parser.parse_args()
    info = bootstrap_portable_python_dlls(heal_layout=True)
    log_line(f"portable_dll_bootstrap: {info}")
    if args.heal_only:
        raise SystemExit(0)
    try:
        import greenlet  # noqa: F401
        from greenlet._greenlet import _C_API  # noqa: F401

        log_line("greenlet ok")
    except Exception as exc:
        log_line(f"greenlet failed: {type(exc).__name__}: {exc}", err=True)
        raise SystemExit(1) from exc
    raise SystemExit(0)
