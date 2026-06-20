#!/usr/bin/env python3
"""Diagnose portable Python native extension load failures on Windows."""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path


def _prefix(msg: str) -> str:
    return f"diagnose: {msg}"


def _load_manifest(bundle_dir: Path) -> dict | None:
    manifest_path = bundle_dir / "RUNTIME_MANIFEST.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(_prefix(f"failed to read RUNTIME_MANIFEST.json: {exc}"))
        return None


def _manifest_entry(manifest: dict | None, suffix: str) -> dict | None:
    if not manifest:
        return None
    suffix = suffix.replace("\\", "/")
    for entry in manifest.get("files", []):
        rel = str(entry.get("relative", "")).replace("\\", "/")
        if rel.endswith(suffix) or suffix in rel:
            return entry
    return None


def _win32_load_error(path: Path) -> str:
    if os.name != "nt":
        return "skipped (not Windows)"
    try:
        import ctypes
        from ctypes import wintypes
    except Exception as exc:
        return f"ctypes unavailable: {exc}"

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
    kernel32.LoadLibraryW.restype = wintypes.HMODULE
    handle = kernel32.LoadLibraryW(str(path))
    if handle:
        kernel32.FreeLibrary(handle)
        return "LoadLibraryW ok"
    err = ctypes.get_last_error()
    hints = {
        126: "module or dependency DLL not found (antivirus/path/VC++ runtime)",
        193: "not a valid Win32 application (arch mismatch or corrupt file)",
        127: "procedure not found (corrupt or wrong binary)",
    }
    hint = hints.get(err, "see Win32 error code documentation")
    return f"LoadLibraryW failed win32={err} ({hint})"


def _check_file(label: str, path: Path, manifest: dict | None, manifest_suffix: str) -> None:
    print(_prefix(f"{label}: {path}"))
    if not path.is_file():
        print(_prefix(f"  MISSING"))
        return
    size = path.stat().st_size
    print(_prefix(f"  size={size}"))
    entry = _manifest_entry(manifest, manifest_suffix)
    if entry:
        expected_size = entry.get("size")
        if expected_size is not None and int(expected_size) != size:
            print(_prefix(f"  manifest size mismatch (expected {expected_size})"))
        else:
            print(_prefix("  manifest size ok"))
    if path.suffix.lower() in {".pyd", ".dll"}:
        print(_prefix(f"  {_win32_load_error(path)}"))


def main() -> int:
    try:
        import portable_dll_bootstrap

        info = portable_dll_bootstrap.bootstrap_portable_python_dlls(heal_layout=True)
        print(_prefix(f"bootstrap {info}"))
    except Exception as exc:
        print(_prefix(f"bootstrap skipped: {type(exc).__name__}: {exc}"))

    bundle_dir = os.environ.get("HUOKE_BUNDLE_DIR", "").strip()
    python_exe = os.environ.get("HUOKE_PYTHON_EXE", "").strip()
    if not python_exe:
        python_exe = sys.executable
    python_root = Path(python_exe).resolve().parent
    if (python_root / "bin" / "python.exe").exists() or python_root.name == "bin":
        python_root = python_root.parent

    if not bundle_dir:
        # Infer bundle from python location: .../runtime/python/python.exe
        if python_root.name == "python" and python_root.parent.name == "runtime":
            bundle_dir = str(python_root.parent.parent)
    bundle_path = Path(bundle_dir) if bundle_dir else None
    manifest = _load_manifest(bundle_path) if bundle_path and bundle_path.is_dir() else None

    print(_prefix(f"python={python_exe}"))
    print(_prefix(f"python_root={python_root}"))
    if bundle_path:
        print(_prefix(f"bundle_dir={bundle_path}"))
    print(_prefix(f"sys.version={sys.version.split()[0]}"))
    print(_prefix(f"PATH head={' | '.join(os.environ.get('PATH', '').split(';')[:5])}"))
    print(_prefix(f"sys.path head={' | '.join(sys.path[:6])}"))

    for name in ("python312.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        _check_file(name, python_root / name, manifest, f"runtime/python/{name}")

    msvc_root = python_root.parent / "msvc"
    if msvc_root.is_dir():
        for dll in sorted(msvc_root.glob("vcruntime*.dll")):
            _check_file(f"msvc/{dll.name}", dll, manifest, f"runtime/msvc/{dll.name}")

    site_packages = python_root / "Lib" / "site-packages"
    greenlet_pyds = sorted(glob.glob(str(site_packages / "greenlet" / "_greenlet*.pyd")))
    if not greenlet_pyds:
        print(_prefix("greenlet pyd: MISSING"))
    for pyd in greenlet_pyds:
        _check_file("greenlet pyd", Path(pyd), manifest, "greenlet/")

    try:
        import greenlet  # noqa: F401
        from greenlet._greenlet import _C_API  # noqa: F401

        print(_prefix("import greenlet: ok"))
    except Exception as exc:
        print(_prefix(f"import greenlet: FAILED ({type(exc).__name__}: {exc})"))
        return 1

    print(_prefix("diagnostics complete"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
