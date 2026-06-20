from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

_STATIC_EXTENSIONS = {
    ".js",
    ".mjs",
    ".css",
    ".map",
    ".json",
    ".woff",
    ".woff2",
    ".ttf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
}


def _is_static_asset_path(path: str) -> bool:
    normalized = path.lstrip("/")
    if normalized.startswith("assets/"):
        return True
    suffix = Path(normalized).suffix.lower()
    return suffix in _STATIC_EXTENSIONS


def mount_desktop_frontend(app: FastAPI, dist_dir: Path) -> None:
    """Desktop 模式：由 FastAPI 托管前端静态资源，与 /api 同源。"""
    import logging

    logger = logging.getLogger(__name__)
    dist = dist_dir.resolve()
    if not dist.is_dir():
        logger.error("desktop frontend dist missing: %s", dist)
        return

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="desktop-assets")

    index_file = dist / "index.html"

    @app.get("/", include_in_schema=False)
    async def desktop_index() -> FileResponse:
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="frontend index missing")
        return FileResponse(index_file)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def desktop_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api") or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = dist / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        if _is_static_asset_path(full_path):
            raise HTTPException(status_code=404, detail="asset not found")
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="frontend index missing")
        return FileResponse(index_file)


def validate_desktop_frontend_dist(dist_dir: Path) -> list[str]:
    """检查 index.html 引用的 JS/CSS 是否存在于 dist 中。"""
    dist = dist_dir.resolve()
    index_file = dist / "index.html"
    if not index_file.is_file():
        return [f"missing index.html under {dist}"]

    html = index_file.read_text(encoding="utf-8")
    refs = re.findall(r"""(?:src|href)=["']([^"']+)["']""", html)
    errors: list[str] = []
    for ref in refs:
        if ref.startswith("http://") or ref.startswith("https://") or ref.startswith("data:"):
            continue
        rel = ref.lstrip("/")
        if not rel:
            continue
        target = dist / rel
        if not target.is_file():
            errors.append(f"broken frontend reference: {ref}")
    return errors
