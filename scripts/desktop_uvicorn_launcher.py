#!/usr/bin/env python3
"""Desktop backend entry: unified preflight + uvicorn in one Python process."""
from __future__ import annotations

import argparse
import atexit
import os
import sys

from desktop_stdio import configure_desktop_stdio, safe_print

configure_desktop_stdio()

from desktop_port_guard import remove_pid_file, resolve_default_data_dir, write_pid_file


def _ensure_backend_on_path() -> None:
    """PYTHONPATH is only read at interpreter startup; apply it to sys.path here."""
    pythonpath = os.environ.get("PYTHONPATH", "")
    if pythonpath:
        for part in pythonpath.split(os.pathsep):
            part = part.strip()
            if part and part not in sys.path:
                sys.path.insert(0, part)
        return
    bundle = os.environ.get("HUOKE_BUNDLE_DIR", "")
    if bundle:
        candidate = os.path.join(bundle, "backend")
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)


def _register_windows_dll_dirs() -> None:
    try:
        import portable_dll_bootstrap

        portable_dll_bootstrap.bootstrap_portable_python_dlls(heal_layout=True)
        return
    except Exception:
        pass
    if os.name != "nt":
        return
    exe = os.path.abspath(sys.executable)
    base = os.path.dirname(exe)
    runtime_root = os.path.dirname(base)
    candidates = [
        base,
        os.path.join(base, "DLLs"),
        os.path.join(runtime_root, "msvc"),
    ]
    for candidate in candidates:
        if not os.path.isdir(candidate):
            continue
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(candidate)
            except OSError:
                pass
    if os.environ.get("HUOKE_DLL_BOOTSTRAP_DONE") != "1":
        path_prefix = [p for p in candidates if os.path.isdir(p)]
        if path_prefix:
            existing = os.environ.get("PATH", "")
            os.environ["PATH"] = ";".join(path_prefix + ([existing] if existing else []))
        os.environ["HUOKE_DLL_BOOTSTRAP_DONE"] = "1"


def run_lifespan_smoke(app: object) -> None:
    import asyncio

    async def _run() -> None:
        async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
            pass

    asyncio.run(_run())


def run_preflight(*, include_lifespan: bool = False) -> object:
    _ensure_backend_on_path()
    _register_windows_dll_dirs()
    safe_print("preflight: python", sys.version.split()[0], flush=True)

    import greenlet  # noqa: F401
    from greenlet._greenlet import _C_API  # noqa: F401

    safe_print("greenlet ok", flush=True)
    import cryptography  # noqa: F401

    safe_print("cryptography ok", flush=True)
    import pydantic_core  # noqa: F401

    safe_print("pydantic_core ok", flush=True)
    from playwright.async_api import async_playwright  # noqa: F401

    safe_print("playwright ok", flush=True)
    from app.db.bootstrap import ensure_database_schema
    from app.main import app

    safe_print("app.main ok", flush=True)
    ensure_database_schema()
    safe_print("database schema ready", flush=True)
    if include_lifespan:
        run_lifespan_smoke(app)
        safe_print("lifespan ok", flush=True)
    safe_print("preflight unified ok", flush=True)
    return app


def _uvicorn_log_config() -> dict:
    # uvicorn.configure_logging() always patches formatters["default"] and
    # formatters["access"] when use_colors is set — both must be present.
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(levelname)s: %(message)s",
                "use_colors": False,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": False,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    try:
        app = run_preflight(include_lifespan=args.check_only)
    except Exception as exc:
        safe_print(f"preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        try:
            import traceback

            traceback.print_exc(file=sys.stderr)
        except OSError:
            pass
        return 1

    if args.check_only:
        return 0

    pid_path = resolve_default_data_dir()
    if pid_path is not None:
        write_pid_file(pid_path / "backend.pid", os.getpid())
        atexit.register(lambda: remove_pid_file(pid_path / "backend.pid"))

    import uvicorn

    safe_print(f"starting uvicorn on port {args.port}", flush=True)
    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="info",
            log_config=_uvicorn_log_config(),
            use_colors=False,
        )
    except SystemExit as exc:
        code = exc.code
        if code in (0, None):
            return 0
        return int(code) if isinstance(code, int) else 1
    except Exception as exc:
        safe_print(f"uvicorn failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        try:
            import traceback

            traceback.print_exc(file=sys.stderr)
        except OSError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
