from __future__ import annotations

import re
from dataclasses import dataclass

_COORD_AT_RE = re.compile(r"^@([a-z0-9_-]+)/([a-z][a-z0-9_-]*)$", re.IGNORECASE)
_COORD_HUB_RE = re.compile(
    r"^(?:skillhub:)?@?([a-z0-9_-]+)/([a-z][a-z0-9_-]*)$",
    re.IGNORECASE,
)
_CLAWHUB_SLUG_RE = re.compile(r"^([a-z0-9_-]+)--([a-z][a-z0-9_-]*)$", re.IGNORECASE)
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class SkillCoordinate:
    namespace: str
    slug: str
    version: str | None = None


def parse_coordinate(raw: str, *, default_namespace: str = "global") -> SkillCoordinate:
    text = (raw or "").strip()
    if not text:
        raise ValueError("技能坐标不能为空")

    version: str | None = None
    if "@" in text and not text.startswith("@"):
        base, _, ver = text.rpartition("@")
        if ver and _SLUG_RE.match(ver) is None and ver not in {"latest", "beta", "stable"}:
            # skill@1.2.0 style version suffix
            if re.match(r"^[\w.-]+$", ver):
                text = base
                version = ver

    text = text.removeprefix("skillhub:").strip()

    match = _COORD_AT_RE.match(text) or _COORD_HUB_RE.match(text)
    if match:
        return SkillCoordinate(namespace=match.group(1).lower(), slug=match.group(2).lower(), version=version)

    claw = _CLAWHUB_SLUG_RE.match(text)
    if claw:
        return SkillCoordinate(namespace=claw.group(1).lower(), slug=claw.group(2).lower(), version=version)

    if "/" in text:
        ns, slug = text.split("/", 1)
        return SkillCoordinate(namespace=ns.strip().lower(), slug=slug.strip().lower(), version=version)

    if not _SLUG_RE.match(text):
        raise ValueError(f"无效的技能坐标: {raw}")
    return SkillCoordinate(namespace=default_namespace, slug=text.lower(), version=version)


def format_coordinate(coord: SkillCoordinate) -> str:
    if coord.namespace == "global":
        return coord.slug
    return f"@{coord.namespace}/{coord.slug}"
