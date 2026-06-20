from __future__ import annotations

from typing import Any

from app.services.page_diagnosis.contracts import CrawlFailureSignal, Platform
from app.services.page_diagnosis.mappers.common import _base_signal, _blob, _classify_text, _map_from_text


class DouyinFailureMapper:
    platform: Platform = "douyin"

    def map_skill_result(self, result: dict[str, Any], *, operation: str, implementation: str) -> CrawlFailureSignal:
        raw = result.get("failure_signal")
        if isinstance(raw, dict):
            return CrawlFailureSignal.model_validate({**raw, "platform": "douyin", "operation": operation})

        text = _blob(result)
        guard_hints: dict[str, Any] = {}
        if any(k in text for k in ("验证码", "人机验证", "verify_check", "风控")):
            guard_hints["captcha"] = "验证码" in text or "人机验证" in text
            guard_hints["rate_limited"] = "风控" in text or "429" in text
        if "so-landing" in text.lower() or "so_landing" in text.lower():
            guard_hints["automation_blocked"] = True
        if any(k in text for k in ("登录", "cookie", "扫码")):
            guard_hints["login_wall"] = True

        return _map_from_text(
            platform="douyin",
            operation=operation,
            implementation=implementation,
            text=text or "抖音抓取失败",
            guard_hints=guard_hints,
        )

    def map_exception(self, exc: Exception, *, operation: str, implementation: str) -> CrawlFailureSignal:
        text = str(exc)
        guard_hints: dict[str, Any] = {}
        try:
            from app.platforms.douyin.human_guards import HumanBrowseGuardError

            if isinstance(exc, HumanBrowseGuardError):
                failure_class = _classify_text(text)
                if "验证码" in text:
                    guard_hints["captcha"] = True
                if "登录" in text or "cookie" in text.lower():
                    guard_hints["login_wall"] = True
                if "so-landing" in text.lower() or "自动化" in text:
                    guard_hints["automation_blocked"] = True
                return _base_signal(
                    platform="douyin",
                    operation=operation,
                    implementation=implementation,
                    failure_class=failure_class,
                    message=text,
                    guard_hints=guard_hints,
                    page_available=True,
                )
        except Exception:
            pass
        return _map_from_text(
            platform="douyin",
            operation=operation,
            implementation=implementation,
            text=text,
            guard_hints=guard_hints,
        )


async def probe_douyin_page(page) -> dict[str, Any]:
    probe: dict[str, Any] = {}
    try:
        from app.platforms.douyin.human_guards import (
            _detect_login_wall,
            _live_cookie_names,
            is_browser_blocked_page,
            is_captcha_page,
            REQUIRED_LOGIN_COOKIES,
        )

        blocked, reason = await is_browser_blocked_page(page)
        probe["automation_blocked"] = blocked
        probe["captcha"] = await is_captcha_page(page)
        probe["login_wall"] = await _detect_login_wall(page)
        live = await _live_cookie_names(page)
        probe["session_valid"] = bool(live & REQUIRED_LOGIN_COOKIES)
        if reason:
            probe["_context"] = {"block_reason": reason}
        probe["url"] = page.url
        try:
            probe["title"] = await page.title()
        except Exception:
            pass
    except Exception as exc:
        probe["_probe_error"] = str(exc)
    return probe
