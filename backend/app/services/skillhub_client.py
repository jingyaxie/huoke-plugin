from __future__ import annotations

from typing import Any

import httpx

from app.services.skillhub_coords import SkillCoordinate


class SkillHubClientError(Exception):
    pass


class SkillHubClient:
    def __init__(self, registry: str, token: str | None = None) -> None:
        self.registry = registry.rstrip("/")
        self.token = token
        self._api_base = f"{self.registry}/api/cli/v1"

    def _headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    async def _get_json(self, path: str) -> Any:
        url = f"{self._api_base}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=self._headers())
        if resp.status_code in {401, 403}:
            raise SkillHubClientError("SkillHub 认证失败，请配置 API Token")
        if resp.status_code == 404:
            raise SkillHubClientError("SkillHub 资源不存在")
        if resp.status_code >= 400:
            raise SkillHubClientError(f"SkillHub 请求失败: HTTP {resp.status_code}")
        body = resp.json()
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    async def whoami(self) -> dict[str, Any]:
        return await self._get_json("/auth/whoami")

    async def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        from urllib.parse import quote

        q = quote(query or "", safe="")
        return await self._get_json(f"/skills/search?q={q}&limit={limit}")

    async def resolve(
        self,
        namespace: str,
        slug: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        suffix = f"?version={version}" if version else ""
        return await self._get_json(f"/skills/{namespace}/{slug}/resolve{suffix}")

    def download_url(self, namespace: str, slug: str, version: str | None = None) -> str:
        if version:
            return f"{self._api_base}/skills/{namespace}/{slug}/versions/{version}/download"
        return f"{self._api_base}/skills/{namespace}/{slug}/download"

    async def download(self, coord: SkillCoordinate) -> tuple[bytes, dict[str, Any]]:
        resolved = await self.resolve(coord.namespace, coord.slug, coord.version)
        version = str(resolved.get("version") or coord.version or "")
        url = self.download_url(coord.namespace, coord.slug, version or None)
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=self._headers())
        if resp.status_code in {401, 403}:
            raise SkillHubClientError("下载技能需要有效的 SkillHub Token")
        if resp.status_code == 404:
            raise SkillHubClientError(f"技能不存在: @{coord.namespace}/{coord.slug}")
        if resp.status_code >= 400:
            raise SkillHubClientError(f"下载技能包失败: HTTP {resp.status_code}")
        return resp.content, resolved

    async def publish(
        self,
        namespace: str,
        zip_bytes: bytes,
        *,
        visibility: str = "public",
        filename: str = "skill.zip",
    ) -> dict[str, Any]:
        url = f"{self._api_base}/skills/{namespace}/publish"
        headers = self._headers()
        files = {"file": (filename, zip_bytes, "application/zip")}
        data = {"visibility": visibility}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
        if resp.status_code in {401, 403}:
            raise SkillHubClientError("发布技能需要有效的 SkillHub Token")
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise SkillHubClientError(f"发布失败: HTTP {resp.status_code} {detail}")
        body = resp.json()
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    @classmethod
    def from_tenant(cls, settings, tenant_id: str) -> "SkillHubClient":
        from app.services.skillhub_config_store import SkillHubConfigStore

        store = SkillHubConfigStore(settings)
        return cls(registry=store.get_registry(tenant_id), token=store.get_token(tenant_id))
