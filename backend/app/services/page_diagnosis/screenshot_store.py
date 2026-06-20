from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings


def diagnosis_screenshot_dir(settings: Settings, tenant_id: str, job_id: str) -> Path:
    root = settings.storage_root / "tenants" / tenant_id / "diagnosis" / job_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_diagnosis_screenshot(
    settings: Settings,
    *,
    tenant_id: str,
    job_id: str,
    png_bytes: bytes,
) -> str | None:
    if not png_bytes:
        return None
    max_bytes = int(getattr(settings, "page_diagnosis_screenshot_max_bytes", 800_000) or 800_000)
    if len(png_bytes) > max_bytes:
        png_bytes = png_bytes[:max_bytes]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    filename = f"{ts}.png"
    path = diagnosis_screenshot_dir(settings, tenant_id, job_id) / filename
    path.write_bytes(png_bytes)
    return f"tenants/{tenant_id}/diagnosis/{job_id}/{filename}"


def resolve_screenshot_path(settings: Settings, screenshot_ref: str) -> Path | None:
    ref = str(screenshot_ref or "").strip().lstrip("/")
    if not ref or ".." in ref:
        return None
    path = (settings.storage_root / ref).resolve()
    root = settings.storage_root.resolve()
    if not str(path).startswith(str(root)):
        return None
    if not path.is_file():
        return None
    return path


async def capture_page_screenshot(page) -> bytes | None:
    if page is None:
        return None
    try:
        return await page.screenshot(type="png", full_page=False)
    except Exception:
        return None


def screenshot_to_data_url(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"
