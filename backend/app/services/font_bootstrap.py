"""VNC/可见浏览器启动前自动检测并安装 CJK 字体。"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

_logger = logging.getLogger(__name__)

_bootstrap_lock = asyncio.Lock()
_bootstrap_done = False
_zh_font_families: int | None = None


def _install_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "install-cjk-fonts.sh"


def count_zh_font_families() -> int:
    """fc-list :lang=zh 字体族数量；-1 表示无 fc-list。"""
    if not shutil.which("fc-list"):
        return -1
    try:
        completed = subprocess.run(
            ["fc-list", ":lang=zh", "family"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            return 0
        return len([line for line in completed.stdout.splitlines() if line.strip()])
    except Exception:
        return 0


async def _run_install_script() -> None:
    script = _install_script_path()
    if not script.is_file():
        _logger.warning("[fonts] install script missing: %s", script)
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "sh",
            str(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        output = (stdout or b"").decode("utf-8", errors="replace").strip()
        if output:
            for line in output.splitlines():
                _logger.info("[fonts] %s", line)
        if proc.returncode != 0:
            _logger.warning("[fonts] install script exit code %s", proc.returncode)
    except asyncio.TimeoutError:
        _logger.warning("[fonts] install script timed out")
    except Exception as exc:
        _logger.warning("[fonts] install script failed: %s", exc)


async def ensure_cjk_fonts(*, force: bool = False) -> dict[str, object]:
    """确保容器/服务器具备中文渲染字体；成功或已就绪后缓存结果。"""
    global _bootstrap_done, _zh_font_families

    async with _bootstrap_lock:
        count = count_zh_font_families()
        if count > 0 and not force:
            _zh_font_families = count
            _bootstrap_done = True
            return {"ready": True, "zh_families": count, "action": "skip"}

        if _bootstrap_done and not force and count == 0:
            return {"ready": False, "zh_families": 0, "action": "cached_miss"}

        await _run_install_script()
        count = count_zh_font_families()
        _zh_font_families = count if count >= 0 else None
        _bootstrap_done = True
        ready = count > 0
        if ready:
            _logger.info("[fonts] bootstrap ok, zh families=%s", count)
        else:
            _logger.warning(
                "[fonts] bootstrap finished but no :lang=zh fonts (count=%s); "
                "可见浏览器中文可能无法显示，请重建 backend 镜像",
                count,
            )
        return {
            "ready": ready,
            "zh_families": count,
            "action": "install",
        }


async def ensure_cjk_fonts_for_visible_browser(headless: bool) -> None:
    if not headless:
        await ensure_cjk_fonts()
