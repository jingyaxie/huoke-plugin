from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SkillHubConfigOut(BaseModel):
    registry: str
    token_configured: bool
    auto_install_enabled: bool


class SkillHubConfigUpdate(BaseModel):
    registry: str | None = None
    token: str | None = None
    clear_token: bool = False
    auto_install_enabled: bool | None = None


class SkillHubSearchItem(BaseModel):
    namespace: str
    slug: str
    latest_version: str = Field(alias="latestVersion", default="")
    summary: str = ""

    model_config = {"populate_by_name": True}


class SkillHubSearchResponse(BaseModel):
    items: list[SkillHubSearchItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20


class SkillHubInstallRequest(BaseModel):
    coordinate: str | None = Field(
        default=None,
        description="技能坐标：slug、@namespace/slug、namespace--slug 或 skillhub:@namespace/slug",
    )
    namespace: str | None = None
    slug: str | None = None
    version: str | None = None
    overwrite: bool = False
    force: bool = False


class SkillHubInstallResult(BaseModel):
    skill: dict[str, Any]
    namespace: str
    slug: str
    version: str
    package_dir: str
    installed: bool
    message: str


class SkillHubInstalledItem(BaseModel):
    slug: str
    namespace: str
    version: str
    skill_id: str
    package_dir: str
    registry: str
    installed_at: datetime | None = None
    fingerprint: str | None = None


class SkillHubInstalledListResponse(BaseModel):
    items: list[SkillHubInstalledItem] = Field(default_factory=list)


class SkillHubPublishRequest(BaseModel):
    skill_id: str
    namespace: str = "global"
    visibility: Literal["public", "namespace-only", "private"] = "public"


class SkillHubPublishResult(BaseModel):
    namespace: str
    slug: str
    version: str
    visibility: str
