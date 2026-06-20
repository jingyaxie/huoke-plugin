from __future__ import annotations

import asyncio
import json

from app.core.config import Settings
from app.platforms.kuaishou.constants import GRAPHQL_PATH, PLATFORM
from app.platforms.kuaishou.js_constants import (
    DROP_QUERY_KEYS,
    _API_TEMPLATE_EXCLUDES,
    _API_TEMPLATE_MARKERS,
)
from app.platforms.kuaishou.session import KuaishouSessionStore
from app.platforms.session_store import PlatformSessionStore
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_POST_JSON_JS = """async ({ url, body, timeoutMs }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body,
            signal: controller.signal,
        });
        const text = await resp.text();
        if (!text) return {};
        try { return JSON.parse(text); } catch { return { raw: text.slice(0, 300) }; }
    } catch (error) { return { error: String(error) }; }
    finally { clearTimeout(timer); }
}"""

_GRAPHQL_JS = """async ({ payload, timeoutMs }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const resp = await fetch('https://www.kuaishou.com/graphql', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: controller.signal,
        });
        const text = await resp.text();
        if (!text) return {};
        try { return JSON.parse(text); } catch { return { raw: text.slice(0, 300) }; }
    } catch (error) { return { error: String(error) }; }
    finally { clearTimeout(timer); }
}"""


class KuaishouJsApiTool:
    """快手薄浏览器 JS 接口公共能力。"""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        store: PlatformSessionStore | None = None,
        account_id: str = "default",
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.account_id = account_id
        self.platform = PLATFORM
        self.store = store or KuaishouSessionStore(settings)

    @staticmethod
    def _is_usable_api_template(url: str) -> bool:
        if any(ex in url for ex in _API_TEMPLATE_EXCLUDES):
            return False
        return "kuaishou.com/rest/" in url or GRAPHQL_PATH in url

    async def warmup_for_js_api(self, page, captured_urls: list[str]) -> str:
        warmup_url = self.settings.kuaishou_home_url
        await page.goto(warmup_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        return warmup_url

    def _pick_device_param_url(self, captured_urls: list[str] | None) -> str | None:
        donors = ("search/feed", "profile/get", "relation/follow")
        for marker in donors:
            for url in reversed(captured_urls or []):
                if marker in url and self._is_usable_api_template(url):
                    return url
        for url in reversed(captured_urls or []):
            if self._is_usable_api_template(url):
                return url
        return None

    async def pick_api_template_url(self, page, captured_urls: list[str] | None = None) -> str:
        device_tpl = self._pick_device_param_url(captured_urls)
        if device_tpl:
            return device_tpl
        candidates = list(captured_urls or [])
        resource_url = await page.evaluate(
            """() => {
                const entries = performance.getEntriesByType('resource').map(e => e.name);
                for (let i = entries.length - 1; i >= 0; i--) {
                    const u = entries[i];
                    if (u.includes('kuaishou.com/rest/v/')) return u;
                }
                return null;
            }"""
        )
        if resource_url:
            candidates.append(resource_url)
        for marker in _API_TEMPLATE_MARKERS:
            for url in reversed(candidates):
                if marker in url and not any(ex in url for ex in _API_TEMPLATE_EXCLUDES):
                    return url
        if candidates:
            return candidates[-1]
        return "https://www.kuaishou.com/rest/v/search/feed"

    async def fetch_json_via_page(self, page, url: str, *, timeout_ms: int = 15000) -> dict:
        try:
            data = await asyncio.wait_for(
                page.evaluate(
                    """async ({ url, timeoutMs }) => {
                        const controller = new AbortController();
                        const timer = setTimeout(() => controller.abort(), timeoutMs);
                        try {
                            const resp = await fetch(url, { credentials: 'include', signal: controller.signal });
                            const text = await resp.text();
                            if (!text) return {};
                            try { return JSON.parse(text); } catch { return {}; }
                        } catch { return {}; }
                        finally { clearTimeout(timer); }
                    }""",
                    {"url": url, "timeoutMs": timeout_ms},
                ),
                timeout=timeout_ms / 1000 + 5,
            )
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def post_json_via_page(self, page, url: str, body: str, *, timeout_ms: int = 15000) -> dict:
        try:
            data = await asyncio.wait_for(
                page.evaluate(_POST_JSON_JS, {"url": url, "body": body, "timeoutMs": timeout_ms}),
                timeout=timeout_ms / 1000 + 5,
            )
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def graphql_via_page(
        self,
        page,
        *,
        operation_name: str,
        query: str,
        variables: dict,
        timeout_ms: int = 15000,
    ) -> dict:
        payload = {
            "operationName": operation_name,
            "variables": variables,
            "query": query,
        }
        try:
            data = await asyncio.wait_for(
                page.evaluate(_GRAPHQL_JS, {"payload": payload, "timeoutMs": timeout_ms}),
                timeout=timeout_ms / 1000 + 5,
            )
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def build_api_url(
        template_url: str,
        path: str,
        *,
        host: str | None = None,
        extra: dict | None = None,
    ) -> str:
        split = urlsplit(template_url)
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        if extra:
            query.update(extra)
        for key in DROP_QUERY_KEYS:
            query.pop(key, None)
        netloc = host or split.netloc or "www.kuaishou.com"
        return urlunsplit((split.scheme or "https", netloc, path, urlencode(query, doseq=True), ""))
