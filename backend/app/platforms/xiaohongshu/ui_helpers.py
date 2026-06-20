from __future__ import annotations

import json
import logging
from typing import Any

from playwright.async_api import BrowserContext, Page

from app.platforms.session_store import PlatformSessionStore

logger = logging.getLogger(__name__)

LOGIN_MODAL_SELECTORS = (
    'input[placeholder*="手机号"]',
    'input[placeholder*="验证码"]',
    "button.submit:has-text('登录')",
    ".login-container",
    ".reds-modal",
)

CLOSE_SELECTORS = (
    ".reds-modal .close",
    ".reds-modal [class*='close']",
    ".login-container [class*='close']",
    "[class*='close-icon']",
    "svg[class*='close']",
    "button:has-text('关闭')",
    "button:has-text('我知道了')",
    ".reds-alert-footer__right",
)

LOGIN_ACTIVATE_URL = "https://edith.xiaohongshu.com/api/sns/web/v1/login/activate"


async def has_login_modal(page: Page) -> bool:
    for selector in LOGIN_MODAL_SELECTORS:
        try:
            if await page.locator(selector).first.count() > 0:
                if await page.locator(selector).first.is_visible():
                    return True
        except Exception:
            continue
    return False


async def dismiss_reds_alert(page: Page) -> dict[str, Any]:
    """关闭小红书通用 alert（如禁言/风险提示），避免遮挡发送按钮。"""
    result: dict[str, Any] = {"dismissed": False, "had_alert": False, "actions": []}

    try:
        has_alert = await page.locator(".reds-alert, .reds-alert-mask").first.count() > 0
    except Exception:
        has_alert = False
    if not has_alert:
        return result
    result["had_alert"] = True

    for selector in (
        "button:has-text('我知道了')",
        ".reds-alert-footer__right",
        ".reds-alert .close",
        ".reds-alert [class*='close']",
    ):
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0 or not await locator.is_visible():
                continue
            await locator.click(force=True, timeout=2000)
            result["actions"].append(f"click:{selector}")
            await page.wait_for_timeout(400)
            if await page.locator(".reds-alert-mask").count() == 0:
                result["dismissed"] = True
                return result
        except Exception:
            continue

    try:
        removed = await page.evaluate(
            """() => {
                let count = 0;
                document.querySelectorAll('.reds-alert, .reds-alert-mask').forEach((el) => {
                    el.remove();
                    count += 1;
                });
                return count;
            }"""
        )
        if removed:
            result["actions"].append(f"js_remove:{removed}")
            result["dismissed"] = True
    except Exception:
        pass

    return result


async def dismiss_login_overlay(page: Page) -> dict[str, Any]:
    """尝试关闭小红书登录弹窗/遮罩。"""
    result: dict[str, Any] = {"dismissed": False, "had_modal": False, "actions": []}

    if not await has_login_modal(page):
        return result
    result["had_modal"] = True

    try:
        await page.keyboard.press("Escape")
        result["actions"].append("escape")
        await page.wait_for_timeout(400)
    except Exception:
        pass

    if not await has_login_modal(page):
        result["dismissed"] = True
        return result

    for selector in CLOSE_SELECTORS:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            await locator.click(force=True, timeout=2000)
            result["actions"].append(f"click:{selector}")
            await page.wait_for_timeout(500)
            if not await has_login_modal(page):
                result["dismissed"] = True
                return result
        except Exception:
            continue

    for selector in (".reds-mask", ".mask", "[class*='mask']"):
        try:
            mask = page.locator(selector).first
            if await mask.count() == 0:
                continue
            box = await mask.bounding_box()
            if not box:
                continue
            await page.mouse.click(box["x"] + 5, box["y"] + 5)
            result["actions"].append(f"mask_click:{selector}")
            await page.wait_for_timeout(500)
            if not await has_login_modal(page):
                result["dismissed"] = True
                return result
        except Exception:
            continue

    try:
        removed = await page.evaluate(
            """() => {
                const selectors = [
                    '.reds-modal', '.login-container', '.login-modal',
                    '[class*="login-container"]', '[class*="login-modal"]',
                ];
                let count = 0;
                for (const sel of selectors) {
                    document.querySelectorAll(sel).forEach((el) => {
                        el.remove();
                        count += 1;
                    });
                }
                document.querySelectorAll('.reds-mask, [class*="mask"]').forEach((el) => {
                    const style = window.getComputedStyle(el);
                    if (style.position === 'fixed' || style.position === 'absolute') {
                        el.remove();
                        count += 1;
                    }
                });
                document.body.style.overflow = 'auto';
                return count;
            }"""
        )
        if removed:
            result["actions"].append(f"js_remove:{removed}")
            await page.wait_for_timeout(300)
            if not await has_login_modal(page):
                result["dismissed"] = True
    except Exception:
        pass

    return result


async def fetch_user_me(page: Page) -> dict[str, Any]:
    """读取 /user/me，用于区分扫码用户与游客态。"""
    try:
        data = await page.evaluate(
            """async () => {
                const resp = await fetch('https://edith.xiaohongshu.com/api/sns/web/v2/user/me', {
                    credentials: 'include',
                });
                const text = await resp.text();
                try {
                    return { status: resp.status, body: JSON.parse(text) };
                } catch {
                    return { status: resp.status, raw: text.slice(0, 300) };
                }
            }"""
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid_user_me"}
    body = data.get("body") if isinstance(data.get("body"), dict) else {}
    inner = body.get("data") if isinstance(body.get("data"), dict) else {}
    guest = inner.get("guest")
    return {
        "ok": body.get("success") is True and body.get("code") == 0,
        "guest": guest,
        "user_id": inner.get("user_id"),
        "status": data.get("status"),
        "raw": body,
    }


async def activate_session(page: Page) -> dict[str, Any]:
    """用已登录 Cookie 激活小红书 Web 会话（须在小红书页面上下文内 fetch）。"""
    try:
        data = await page.evaluate(
            """async () => {
                const resp = await fetch('https://edith.xiaohongshu.com/api/sns/web/v1/login/activate', {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json;charset=UTF-8',
                        'Accept': 'application/json, text/plain, */*',
                    },
                    body: '{}',
                });
                const text = await resp.text();
                try {
                    return { status: resp.status, body: JSON.parse(text) };
                } catch {
                    return { status: resp.status, raw: text.slice(0, 300) };
                }
            }"""
        )
    except Exception as exc:
        logger.debug("xhs activate_session failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid_activate_response"}
    body = data.get("body") if isinstance(data.get("body"), dict) else {}
    status = int(data.get("status") or 0)
    ok = status == 200 and (body.get("success") is True or body.get("code") == 0)
    return {"ok": ok, "status": status, "data": body or data}


async def prepare_logged_in_page(page: Page) -> dict[str, Any]:
    """已登录时关闭误弹登录窗并激活会话；游客态保留扫码/登录弹窗供用户操作。"""
    user_me = await fetch_user_me(page)
    dismiss: dict[str, Any] = {"dismissed": False, "had_modal": False, "actions": []}
    if user_me.get("guest") is False:
        dismiss = await dismiss_login_overlay(page)
        if dismiss.get("had_modal"):
            dismiss = await dismiss_login_overlay(page)
    activate = await activate_session(page)
    if user_me.get("guest") is not False:
        user_me = await fetch_user_me(page)
    return {"dismiss": dismiss, "activate": activate, "user_me": user_me}


async def ensure_logged_in_user(page: Page) -> dict[str, Any]:
    """确保非游客态；guest=true 时返回明确错误。"""
    prep = await prepare_logged_in_page(page)
    user_me = prep.get("user_me") if isinstance(prep.get("user_me"), dict) else {}
    if user_me.get("guest") is False:
        return {"ok": True, "user_id": user_me.get("user_id"), "prep": prep}
    if user_me.get("guest") is True:
        return {
            "ok": False,
            "error": "当前为小红书游客态(guest=true)，评论回复需要扫码登录真实账号，请重新绑定后再试",
            "prep": prep,
        }
    return {
        "ok": False,
        "error": "无法确认小红书登录态，请重新扫码登录",
        "prep": prep,
    }


async def should_persist_login(page: Page) -> bool:
    """小红书仅有 Cookie 不够，须 user/me 返回 guest=false 才允许落盘。"""
    try:
        user_me = await fetch_user_me(page)
    except Exception:
        return False
    return user_me.get("guest") is False


async def save_login_if_authenticated(
    page: Page,
    context: BrowserContext,
    store: PlatformSessionStore,
    tenant_id: str,
    account_id: str = "default",
    *,
    rebake_profile: bool = False,
) -> dict[str, Any]:
    """激活会话并仅在真实登录态时写入 storage_state；可选同步持久化 Profile。"""
    login = await ensure_logged_in_user(page)
    if not login.get("ok"):
        return {"saved": False, **login}
    path = await store.save_from_context(tenant_id, context, account_id)
    from app.platforms.xiaohongshu.session_meta import record_authenticated_snapshot

    await record_authenticated_snapshot(
        store, tenant_id, account_id, page, user_id=login.get("user_id")
    )
    result: dict[str, Any] = {
        "saved": True,
        "ok": True,
        "user_id": login.get("user_id"),
        "path": str(path),
        "prep": login.get("prep"),
    }
    if rebake_profile:
        from app.platforms.xiaohongshu.persistence import rebake_persistent_profile

        result["profile_sync"] = await rebake_persistent_profile(
            store.settings, store, tenant_id, account_id
        )
    return result
