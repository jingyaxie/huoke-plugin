"""Make desktop backend logging safe when stdout/stderr are piped or missing (Windows)."""
from __future__ import annotations

import io
import os
import sys
from typing import TextIO


class SafeTextIO(io.TextIOBase):
    """Never raise on write/flush — piped or headless Windows consoles can EINVAL."""

    def __init__(self, underlying: TextIO | None, *, name: str = "stdout") -> None:
        self._underlying = underlying
        self._name = name
        self._log_path = (os.environ.get("HUOKE_LOG_FILE") or "").strip() or None

    def write(self, text: str) -> int:  # type: ignore[override]
        if not text:
            return 0
        written = 0
        if self._underlying is not None:
            try:
                written = self._underlying.write(text)
            except OSError:
                written = len(text)
        else:
            written = len(text)
        if self._log_path:
            try:
                with open(self._log_path, "a", encoding="utf-8") as handle:
                    handle.write(text)
            except OSError:
                pass
        return written

    def flush(self) -> None:
        if self._underlying is not None:
            try:
                self._underlying.flush()
            except OSError:
                pass

    def isatty(self) -> bool:
        return False


def configure_desktop_stdio() -> None:
    """Call before any print/logging in desktop backend child processes."""
    if getattr(configure_desktop_stdio, "_done", False):
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "write"):
            log_path = (os.environ.get("HUOKE_LOG_FILE") or "").strip()
            if log_path:
                try:
                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                    stream = open(log_path, "a", encoding="utf-8", buffering=1)
                except OSError:
                    stream = open(os.devnull, "w", encoding="utf-8")
            else:
                stream = open(os.devnull, "w", encoding="utf-8")
        setattr(sys, name, SafeTextIO(stream, name=name))
    configure_desktop_stdio._done = True  # type: ignore[attr-defined]


def safe_print(*args, **kwargs) -> None:
    try:
        print(*args, **kwargs)
    except OSError:
        text = " ".join(str(arg) for arg in args)
        log_path = (os.environ.get("HUOKE_LOG_FILE") or "").strip()
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(text + "\n")
            except OSError:
                pass


def configure_pipe_stdio() -> None:
    """Alias kept for portable_dll_bootstrap and other legacy callers."""
    configure_desktop_stdio()


def log_line(message: str, *, err: bool = False) -> None:
    """Write one line without raising on broken pipe / flush errors."""
    targets = (sys.stderr, sys.stdout) if err else (sys.stdout, sys.stderr)
    for target in targets:
        if target is None:
            continue
        try:
            print(message, file=target)
            return
        except OSError:
            continue
