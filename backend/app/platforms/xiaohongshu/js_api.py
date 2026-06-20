from __future__ import annotations

import asyncio
import json

from app.core.config import Settings
from app.platforms.session_store import PlatformSessionStore
from app.platforms.xiaohongshu.js_constants import (
    DROP_QUERY_KEYS,
    EDITH_HOST,
    PLATFORM,
    _API_TEMPLATE_EXCLUDES,
    _API_TEMPLATE_MARKERS,
)
from app.platforms.xiaohongshu.session import XhsSessionStore
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_POST_SIGNED_JSON_JS = """async ({ path, payload, referer, timeoutMs }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        if (typeof window._webmsxyw !== 'function') {
            return { error: 'missing_webmsxyw_signer' };
        }
        const sign = await window._webmsxyw(path, payload);
        const url = path.startsWith('http') ? path : ('https://edith.xiaohongshu.com' + path);
        const headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'Accept': 'application/json, text/plain, */*',
            'Origin': 'https://www.xiaohongshu.com',
            'Referer': referer,
            'X-s': sign['X-s'],
            'X-t': String(sign['X-t']),
        };
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers,
            body: JSON.stringify(payload),
            signal: controller.signal,
        });
        const text = await resp.text();
        if (!text) return { status: resp.status };
        try { return { ...JSON.parse(text), status: resp.status }; } catch { return { raw: text.slice(0, 300), status: resp.status }; }
    } catch (error) { return { error: String(error) }; }
    finally { clearTimeout(timer); }
}"""

_POST_JSON_JS = """async ({ url, body, referer, timeoutMs }) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'Accept': 'application/json, text/plain, */*',
        };
        if (referer) {
            headers.Origin = 'https://www.xiaohongshu.com';
            headers.Referer = referer;
        }
        const resp = await fetch(url, {
            method: 'POST',
            credentials: 'include',
            headers,
            body,
            signal: controller.signal,
        });
        const text = await resp.text();
        if (!text) return { status: resp.status };
        try { return { ...JSON.parse(text), status: resp.status }; } catch { return { raw: text.slice(0, 300), status: resp.status }; }
    } catch (error) { return { error: String(error) }; }
    finally { clearTimeout(timer); }
}"""


class XhsJsApiTool:
    """小红书薄浏览器 JS 接口公共能力。"""

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
        self.store = store or XhsSessionStore(settings)

    @staticmethod
    def _is_usable_api_template(url: str) -> bool:
        if any(ex in url for ex in _API_TEMPLATE_EXCLUDES):
            return False
        return EDITH_HOST in url or "xiaohongshu.com/api/sns" in url

    async def warmup_for_js_api(self, page, captured_urls: list[str]) -> str:
        warmup_url = self.settings.xhs_explore_url or self.settings.xhs_home_url
        await page.goto(warmup_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        return warmup_url

    def _pick_device_param_url(self, captured_urls: list[str] | None) -> str | None:
        donors = (
            "search/notes",
            "homefeed",
            "comment/page",
            "user/otherinfo",
        )
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
                    if (u.includes('edith.xiaohongshu.com/api/sns/web/')) {
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
                    return url
        for url in reversed(candidates):
            if self._is_usable_api_template(url):
                return url
        if candidates:
            return candidates[-1]
        return f"https://{EDITH_HOST}/api/sns/web/v2/comment/page?"

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

    async def post_signed_json_via_page(
        self,
        page,
        path: str,
        payload: dict,
        *,
        timeout_ms: int = 15000,
        referer: str | None = None,
    ) -> dict:
        """经页面 _webmsxyw 签名后 POST（comment/post 等接口必需）。"""
        try:
            data = await asyncio.wait_for(
                page.evaluate(
                    _POST_SIGNED_JSON_JS,
                    {
                        "path": path,
                        "payload": payload,
                        "timeoutMs": timeout_ms,
                        "referer": referer or page.url or self.settings.xhs_explore_url,
                    },
                ),
                timeout=timeout_ms / 1000 + 5,
            )
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def post_json_via_page(
        self,
        page,
        url: str,
        payload: dict,
        *,
        timeout_ms: int = 15000,
        referer: str | None = None,
    ) -> dict:
        try:
            data = await asyncio.wait_for(
                page.evaluate(
                    _POST_JSON_JS,
                    {
                        "url": url,
                        "body": json.dumps(payload, ensure_ascii=False),
                        "timeoutMs": timeout_ms,
                        "referer": referer or page.url or self.settings.xhs_explore_url,
                    },
                ),
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
        netloc = host or split.netloc or EDITH_HOST
        return urlunsplit((split.scheme or "https", netloc, path, urlencode(query, doseq=True), ""))
