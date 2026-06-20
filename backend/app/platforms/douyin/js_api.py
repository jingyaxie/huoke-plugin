from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import Settings
from app.platforms.douyin.js_constants import (
    DROP_QUERY_KEYS,
    _API_TEMPLATE_EXCLUDES,
    _API_TEMPLATE_MARKERS,
    _FIRE_FETCH_JS,
)
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore

PLATFORM = "douyin"

_POST_FORM_JS = """async ({ url, body, timeoutMs }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body,
            signal: controller.signal,
        });
        const text = await resp.text();
        if (!text) return {};
        try { return JSON.parse(text); } catch { return { raw: text.slice(0, 300) }; }
    } catch (error) { return { error: String(error) }; }
    finally { clearTimeout(timer); }
}"""


class DouyinJsApiTool:
    """抖音薄浏览器 JS 接口公共能力。"""

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
        self.store = store or DouyinSessionStore(settings)

    @staticmethod
    def _is_usable_api_template(url: str) -> bool:
        if any(ex in url for ex in _API_TEMPLATE_EXCLUDES):
            return False
        query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        return bool(query.get("webid") or query.get("uifid"))


    async def warmup_for_js_api(self, page, captured_urls: list[str]) -> str:
        """薄浏览器：只打开首页预热签名，不点页面、不新开 tab。"""
        warmup_url = self.settings.douyin_home_url
        await page.goto(warmup_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        return warmup_url


    def _pick_device_param_url(self, captured_urls: list[str] | None) -> str | None:
        donors = (
            "general/search/single",
            "search/item",
            "search/sug",
            "suggest_words",
            "aweme/post",
        )
        for marker in donors:
            for url in reversed(captured_urls or []):
                if marker in url and self._is_usable_api_template(url):
                    return url
        for url in reversed(captured_urls or []):
            if "hot/search/list" in url:
                continue
            if self._is_usable_api_template(url):
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
                    if (u.includes('douyin.com/aweme/v1/web/') && !u.includes('comment/list')) {
                        return u;
                    }
                }
                return null;
            }"""
        )
        if resource_url:
            candidates.append(resource_url)
        for marker in _API_TEMPLATE_MARKERS:
            for url in reversed(candidates):
                if marker in url and not any(ex in url for ex in _API_TEMPLATE_EXCLUDES):
                    if marker in {"suggest_words", "search/sug", "general/search", "search/single", "search/item"}:
                        return url
                    if self._is_usable_api_template(url):
                        return url
        for url in reversed(candidates):
            if not any(ex in url for ex in _API_TEMPLATE_EXCLUDES) and self._is_usable_api_template(url):
                return url
        if candidates:
            return candidates[-1]
        return (
            "https://www.douyin.com/aweme/v1/web/general/search/single/"
            "?device_platform=webapp&aid=6383&channel=channel_pc_web&pc_client_type=1"
        )


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
                            try {
                                return JSON.parse(text);
                            } catch {
                                return {};
                            }
                        } catch {
                            return {};
                        } finally {
                            clearTimeout(timer);
                        }
                    }""",
                    {"url": url, "timeoutMs": timeout_ms},
                ),
                timeout=timeout_ms / 1000 + 5,
            )
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}


    async def post_form_via_page(self, page, url: str, body: str, *, timeout_ms: int = 15000) -> dict:
        try:
            data = await asyncio.wait_for(
                page.evaluate(_POST_FORM_JS, {"url": url, "body": body, "timeoutMs": timeout_ms}),
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
        netloc = host or split.netloc or "www.douyin.com"
        return urlunsplit((split.scheme or "https", netloc, path, urlencode(query, doseq=True), ""))
