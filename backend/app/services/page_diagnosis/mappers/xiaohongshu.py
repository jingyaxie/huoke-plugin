from __future__ import annotations

from typing import Any

from app.services.page_diagnosis.contracts import CrawlFailureSignal, Platform
from app.services.page_diagnosis.mappers.common import _base_signal, _blob, _classify_text, _map_from_text


class XiaohongshuFailureMapper:
    platform: Platform = "xiaohongshu"

    def map_skill_result(self, result: dict[str, Any], *, operation: str, implementation: str) -> CrawlFailureSignal:
        raw = result.get("failure_signal")
        if isinstance(raw, dict):
            return CrawlFailureSignal.model_validate({**raw, "platform": "xiaohongshu", "operation": operation})

        text = _blob(result)
        guard_hints: dict[str, Any] = {}
        lower = text.lower()
        if "游客" in text or "visitor" in lower or "guest" in lower:
            guard_hints["guest_mode"] = True
            guard_hints["login_wall"] = True
        if any(k in text for k in ("验证码", "安全验证", "风控")):
            guard_hints["captcha"] = "验证码" in text or "安全验证" in text
            guard_hints["rate_limited"] = "风控" in text
        if any(k in text for k in ("登录", "cookie", "扫码")):
            guard_hints["login_wall"] = True

        failure_class = _classify_text(text)
        if guard_hints.get("guest_mode"):
            failure_class = "auth_required"

        return _base_signal(
            platform="xiaohongshu",
            operation=operation,
            implementation=implementation,
            failure_class=failure_class,
            message=text or "小红书抓取失败",
            guard_hints=guard_hints,
        )

    def map_exception(self, exc: Exception, *, operation: str, implementation: str) -> CrawlFailureSignal:
        return _map_from_text(
            platform="xiaohongshu",
            operation=operation,
            implementation=implementation,
            text=str(exc),
        )


async def probe_xiaohongshu_page(page) -> dict[str, Any]:
    probe: dict[str, Any] = {}
    try:
        body = ""
        try:
            body = (await page.locator("body").inner_text(timeout=2000))[:1500]
        except Exception:
            pass
        lower = body.lower()
        probe["guest_mode"] = "登录" in body and ("扫码" in body or "登录后" in body)
        probe["login_wall"] = ".login-container" in body or "扫码登录" in body or probe["guest_mode"]
        probe["captcha"] = "验证码" in body or "安全验证" in body
        probe["rate_limited"] = "频繁" in body or "风控" in body
        probe["url"] = page.url
        try:
            probe["title"] = await page.title()
        except Exception:
            pass
        if "xiaohongshu" not in lower and page.url:
            probe["_context"] = {"note": "non_xhs_page"}
    except Exception as exc:
        probe["_probe_error"] = str(exc)
    return probe
