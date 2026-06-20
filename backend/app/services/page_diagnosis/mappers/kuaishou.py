from __future__ import annotations

from typing import Any

from app.services.page_diagnosis.contracts import CrawlFailureSignal, Platform
from app.services.page_diagnosis.mappers.common import _blob, _classify_text, _map_from_text


class KuaishouFailureMapper:
    platform: Platform = "kuaishou"

    def map_skill_result(self, result: dict[str, Any], *, operation: str, implementation: str) -> CrawlFailureSignal:
        raw = result.get("failure_signal")
        if isinstance(raw, dict):
            return CrawlFailureSignal.model_validate({**raw, "platform": "kuaishou", "operation": operation})

        text = _blob(result)
        guard_hints: dict[str, Any] = {}
        if any(k in text for k in ("验证码", "滑块")):
            guard_hints["captcha"] = True
        if any(k in text for k in ("登录", "cookie", "扫码")):
            guard_hints["login_wall"] = True
        if any(k in text for k in ("风控", "频繁", "429")):
            guard_hints["rate_limited"] = True

        return _map_from_text(
            platform="kuaishou",
            operation=operation,
            implementation=implementation,
            text=text or "快手抓取失败",
            guard_hints=guard_hints,
        )

    def map_exception(self, exc: Exception, *, operation: str, implementation: str) -> CrawlFailureSignal:
        return _map_from_text(
            platform="kuaishou",
            operation=operation,
            implementation=implementation,
            text=str(exc),
        )


async def probe_kuaishou_page(page) -> dict[str, Any]:
    probe: dict[str, Any] = {}
    try:
        body = ""
        try:
            body = (await page.locator("body").inner_text(timeout=2000))[:1500]
        except Exception:
            pass
        probe["login_wall"] = "登录" in body and ("扫码" in body or "请登录" in body)
        probe["captcha"] = "验证码" in body or "滑块" in body
        probe["rate_limited"] = "频繁" in body or "操作过快" in body
        probe["url"] = page.url
        try:
            probe["title"] = await page.title()
        except Exception:
            pass
    except Exception as exc:
        probe["_probe_error"] = str(exc)
    return probe
