from __future__ import annotations

import re
from typing import Any

from app.core.config import Settings
from app.services.skillhub_config_store import SkillHubConfigStore
from app.services.skillhub_coords import format_coordinate, parse_coordinate
from app.services.skillhub_installer import SkillHubInstaller

# skillhub:install pdf-parser / @team/slug / 安装技能 xxx
_INSTALL_PATTERNS = [
    re.compile(
        r"(?:skillhub:)?install\s+(@?[a-z0-9_-]+(?:/[a-z][a-z0-9_-]*)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:安装|装)\s*(?:技能|skill)?\s*[`'\"]?(@?[a-z0-9_-]+(?:--[a-z][a-z0-9_-]+)?(?:/[a-z][a-z0-9_-]*)?)[`'\"]?",
        re.IGNORECASE,
    ),
    re.compile(
        r"skillhub:([@a-z0-9_-]+(?:/[a-z][a-z0-9_-]*)?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"@(?:global|skillhub)/([a-z][a-z0-9_-]+)",
        re.IGNORECASE,
    ),
]


def detect_install_coordinates(message: str) -> list[str]:
    found: list[str] = []
    for pattern in _INSTALL_PATTERNS:
        for match in pattern.finditer(message):
            coord = match.group(1).strip()
            if coord and coord not in found:
                found.append(coord)
    return found


async def auto_install_from_message(
    settings: Settings,
    tenant_id: str,
    message: str,
) -> list[dict[str, Any]]:
    config = SkillHubConfigStore(settings)
    if not config.is_auto_install_enabled(tenant_id):
        return []

    coords = detect_install_coordinates(message)
    if not coords:
        return []

    installer = SkillHubInstaller(settings, tenant_id)
    results: list[dict[str, Any]] = []
    for raw in coords:
        try:
            coord = parse_coordinate(raw)
            result = await installer.install(coordinate=format_coordinate(coord), overwrite=False)
            results.append(result)
        except Exception as exc:
            results.append({"coordinate": raw, "error": str(exc), "installed": False})
    return results
