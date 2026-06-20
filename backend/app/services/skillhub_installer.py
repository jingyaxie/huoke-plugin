from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.platforms.tenant import normalize_tenant_id
from app.schemas.skill import SkillCreate, SkillOut, SkillUpdate
from app.services.skillhub_client import SkillHubClient, SkillHubClientError
from app.services.skillhub_coords import SkillCoordinate, format_coordinate, parse_coordinate
from app.services.skillhub_config_store import SkillHubConfigStore
from app.services.skillhub_package import (
    extract_zip_to_dir,
    parse_skill_md_from_package,
    write_metadata,
)
from app.services.skill_store import SkillStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SkillHubInstaller:
    def __init__(self, settings: Settings, tenant_id: str) -> None:
        self.settings = settings
        self.tenant_id = normalize_tenant_id(tenant_id)
        self.config_store = SkillHubConfigStore(settings)
        self.skill_store = SkillStore(settings)
        self.client = SkillHubClient.from_tenant(settings, self.tenant_id)

    def packages_root(self) -> Path:
        root = self.settings.storage_root / "tenants" / self.tenant_id / "skill_packages"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def installs_index_path(self) -> Path:
        return self.packages_root() / "installs.json"

    def package_dir(self, slug: str) -> Path:
        return self.packages_root() / slug

    def _load_installs(self) -> list[dict[str, Any]]:
        path = self.installs_index_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return list(data.get("installs") or [])
        except json.JSONDecodeError:
            return []

    def _save_installs(self, installs: list[dict[str, Any]]) -> None:
        path = self.installs_index_path()
        path.write_text(
            json.dumps({"installs": installs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_installed(self) -> list[dict[str, Any]]:
        return self._load_installs()

    def _upsert_install_record(
        self,
        *,
        slug: str,
        namespace: str,
        version: str,
        skill_id: str,
        package_dir: str,
        fingerprint: str | None,
    ) -> None:
        installs = self._load_installs()
        record = {
            "slug": slug,
            "namespace": namespace,
            "version": version,
            "skill_id": skill_id,
            "package_dir": package_dir,
            "registry": self.config_store.get_registry(self.tenant_id),
            "installed_at": _utc_now().isoformat(),
            "fingerprint": fingerprint,
        }
        installs = [i for i in installs if i.get("slug") != slug]
        installs.append(record)
        self._save_installs(installs)

    async def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        return await self.client.search(query, limit=limit)

    async def install(
        self,
        *,
        coordinate: str | None = None,
        namespace: str | None = None,
        slug: str | None = None,
        version: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if coordinate:
            coord = parse_coordinate(coordinate)
            if version:
                coord = SkillCoordinate(coord.namespace, coord.slug, version)
        elif slug:
            coord = SkillCoordinate(namespace or "global", slug, version)
        else:
            raise ValueError("请提供 coordinate 或 slug")

        existing = self.skill_store.get(self.tenant_id, coord.slug)
        if existing and not overwrite:
            if getattr(existing, "hub_version", None) == (version or existing.hub_version):
                return {
                    "skill": existing.model_dump(mode="json"),
                    "namespace": coord.namespace,
                    "slug": coord.slug,
                    "version": str(getattr(existing, "hub_version", "") or ""),
                    "package_dir": str(getattr(existing, "package_path", "") or ""),
                    "installed": False,
                    "message": f"技能已安装: {format_coordinate(coord)}",
                }

        try:
            zip_bytes, resolved = await self.client.download(coord)
        except SkillHubClientError as exc:
            raise ValueError(str(exc)) from exc

        resolved_version = str(resolved.get("version") or version or "latest")
        fingerprint = str(resolved.get("fingerprint") or "") or None
        target_dir = self.package_dir(coord.slug)

        extract_zip_to_dir(zip_bytes, target_dir)
        write_metadata(
            target_dir,
            registry=self.config_store.get_registry(self.tenant_id),
            namespace=coord.namespace,
            slug=coord.slug,
            version=resolved_version,
            fingerprint=fingerprint,
        )

        skill_create = parse_skill_md_from_package(target_dir)
        skill_create.source = "skillhub"
        skill_create.package_path = str(target_dir)
        skill_create.hub_namespace = coord.namespace
        skill_create.hub_version = resolved_version
        record_data = skill_create.model_dump()
        existing_skill = self.skill_store.get(self.tenant_id, skill_create.id)
        if existing_skill and existing_skill.scope == "tenant":
            skill_out = self.skill_store.update(
                self.tenant_id,
                skill_create.id,
                SkillUpdate(**{k: v for k, v in record_data.items() if k != "id"}),
            )
        elif existing_skill and existing_skill.scope == "global":
            skill_out = self.skill_store.create(self.tenant_id, skill_create, scope="tenant")
        else:
            skill_out = self.skill_store.create(self.tenant_id, skill_create, scope="tenant")

        self._upsert_install_record(
            slug=coord.slug,
            namespace=coord.namespace,
            version=resolved_version,
            skill_id=skill_out.id,
            package_dir=str(target_dir),
            fingerprint=fingerprint,
        )

        return {
            "skill": skill_out.model_dump(mode="json"),
            "namespace": coord.namespace,
            "slug": coord.slug,
            "version": resolved_version,
            "package_dir": str(target_dir),
            "installed": True,
            "message": f"已从 SkillHub 安装 {format_coordinate(coord)} v{resolved_version}",
        }

    def uninstall(self, slug: str) -> bool:
        target_dir = self.package_dir(slug)
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        installs = [i for i in self._load_installs() if i.get("slug") != slug]
        self._save_installs(installs)
        try:
            return self.skill_store.delete(self.tenant_id, slug)
        except ValueError:
            # global skill — disable via tenant override
            skill = self.skill_store.get(self.tenant_id, slug)
            if skill:
                self.skill_store.update(self.tenant_id, slug, SkillUpdate(enabled=False))
                return True
            return False

    async def publish_local_skill(
        self,
        skill_id: str,
        *,
        namespace: str = "global",
        visibility: str = "public",
    ) -> dict[str, Any]:
        skill = self.skill_store.get(self.tenant_id, skill_id)
        if skill is None:
            raise ValueError(f"技能不存在: {skill_id}")
        package_path = getattr(skill, "package_path", None)
        if not package_path or not Path(package_path).is_dir():
            raise ValueError("仅支持发布已安装 SkillHub 包目录的技能，请先安装或上传技能包")

        import zipfile
        from io import BytesIO

        buf = BytesIO()
        root = Path(package_path)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in root.rglob("*"):
                if path.is_file() and not str(path).startswith(str(root / ".skillhub")):
                    zf.write(path, path.relative_to(root).as_posix())
        result = await self.client.publish(namespace, buf.getvalue(), visibility=visibility)
        return result
