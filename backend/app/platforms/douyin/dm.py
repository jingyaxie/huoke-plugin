from __future__ import annotations

import contextlib
import json
from datetime import datetime
from pathlib import Path

from app.core.antibot import headless_for_platform, require_login
from app.core.config import Settings
from app.platforms.douyin.profile import DouyinProfileTool
from app.platforms.douyin.session import DouyinSessionStore
from app.platforms.session_store import PlatformSessionStore
from app.services.playwright_pool import PlaywrightPool

PLATFORM = "douyin"

_DM_BUTTON_SELECTORS = (
    '[data-e2e="user-detail"] button:has-text("私信")',
    '[data-e2e="user-info-message-btn"]',
    '[data-e2e="user-info"] button:has-text("私信")',
    'button:has-text("私信")',
)

_PROFILE_PANEL_INPUT_SELECTORS = (
    '[data-e2e="msg-input"] div[contenteditable="true"]',
    '[data-e2e="msg-input"] .editor-kit-container',
    '[data-e2e="msg-input"] div.zone-container.editor-kit-container',
)

_PROFILE_PANEL_SEND_SELECTORS = (
    '[data-e2e="msg-input"] .messageMsgInputinputAction',
    '[data-e2e="msg-input"] button:has-text("发送")',
)

_IM_INPUT_SELECTORS = (
    '[data-e2e="im-dialog"] [data-e2e="message-input"]',
    '[data-e2e="im-dialog"] textarea',
    '[data-e2e="im-dialog"] div[contenteditable="true"]',
    '[data-e2e="message-input"]',
)


class DouyinDmTool:
    """抖音私信工具（主页点击私信 → 嵌入式 msg-input 或 im-dialog 弹层发送）。"""

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
        self._profile = DouyinProfileTool(settings, tenant_id, self.store, account_id=account_id)

    async def send_message(
        self,
        *,
        sec_uid: str,
        message: str,
        username: str = "",
        show_browser: bool = False,
    ) -> dict:
        require_login(self.store, self.tenant_id, self.settings, account_id=self.account_id)
        if not sec_uid:
            raise ValueError("缺少 sec_uid")
        if not (message or "").strip():
            raise ValueError("发送私信需要 message")

        headless = headless_for_platform(self.settings, PLATFORM, False if show_browser else None)
        pool = PlaywrightPool.get()
        async with pool.tenant_context(
            PLATFORM,
            self.tenant_id,
            self.store,
            self.settings,
            headless=headless,
        ) as (_, page):
            result = await self.send_message_on_page(page, sec_uid=sec_uid, message=message, username=username)

        output = (
            self.settings.report_output_dir
            / f"dm_{self.platform}_{self.tenant_id}_{sec_uid[:12]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_file"] = str(output)
        return result

    async def send_message_on_page(
        self,
        page,
        *,
        sec_uid: str,
        message: str,
        username: str = "",
        require_on_profile: bool = False,
    ) -> dict:
        """在已打开的用户主页 page 上发送私信（不重复 goto）。"""
        on_profile = sec_uid and sec_uid in (page.url or "")
        if not on_profile:
            with contextlib.suppress(Exception):
                on_profile = await page.locator(
                    '[data-e2e="user-detail"], [data-e2e="user-info-follow-btn"]'
                ).count() > 0
        if not on_profile:
            if require_on_profile:
                return {
                    "platform": PLATFORM,
                    "tenant_id": self.tenant_id,
                    "username": username,
                    "user_id": "",
                    "sec_uid": sec_uid,
                    "profile_url": page.url,
                    "page_url": page.url,
                    "capture_method": "profile_dm_ui",
                    "message": {
                        "ok": False,
                        "error": "须先点击评论头像进入用户主页后再私信",
                    },
                }
            profile_url = await self._profile.open_profile(page, sec_uid)
        else:
            profile_url = page.url
        resolved_username = username
        if not resolved_username:
            with contextlib.suppress(Exception):
                nick = page.locator('[data-e2e="user-info"] h1, [data-e2e="user-detail"] h1').first
                if await nick.count():
                    resolved_username = (await nick.inner_text()).strip()

        return {
            "platform": PLATFORM,
            "tenant_id": self.tenant_id,
            "username": resolved_username,
            "user_id": "",
            "sec_uid": sec_uid,
            "profile_url": profile_url,
            "page_url": page.url,
            "capture_method": "profile_dm_ui",
            "message": await self._send_dm_on_profile(page, message),
        }

    async def _send_on_page(self, page, *, sec_uid: str, message: str, username: str) -> dict:
        return await self.send_message_on_page(page, sec_uid=sec_uid, message=message, username=username)

    @staticmethod
    async def _first_visible(page, selectors: tuple[str, ...]):
        for selector in selectors:
            loc = page.locator(selector)
            count = await loc.count()
            for idx in range(count):
                item = loc.nth(idx)
                try:
                    if await item.is_visible():
                        return item, selector
                except Exception:
                    continue
        return None, None

    async def _click_dm_button(self, page) -> dict:
        dm, selector = await self._first_visible(page, _DM_BUTTON_SELECTORS)
        if dm is None:
            clicked = await page.evaluate(
                """() => {
                    const root = document.querySelector('[data-e2e="user-detail"]');
                    if (!root) return false;
                    const btn = Array.from(root.querySelectorAll('button'))
                        .find((el) => (el.textContent || '').includes('私信'));
                    if (!btn) return false;
                    btn.click();
                    return true;
                }"""
            )
            if not clicked:
                return {"ok": False, "error": "dm_button_not_found"}
            selector = "user-detail.button.js_click"
        else:
            await dm.click(force=True)

        await page.wait_for_timeout(1500)
        return {"ok": True, "selector": selector}

    async def _wait_dm_input_surface(self, page, *, timeout_ms: int = 25000):
        deadline = timeout_ms
        step = 1000
        while deadline > 0:
            inp, selector = await self._first_visible(page, _PROFILE_PANEL_INPUT_SELECTORS)
            if inp is not None:
                return "profile_panel", inp, selector
            inp, selector = await self._first_visible(page, _IM_INPUT_SELECTORS)
            if inp is not None:
                return "im_dialog", inp, selector
            await page.wait_for_timeout(step)
            deadline -= step
        return None, None, None

    async def _send_via_profile_panel(self, page, message: str, inp, input_selector: str, opened: dict) -> dict:
        await inp.click()
        try:
            await inp.fill(message)
        except Exception:
            await page.keyboard.type(message)
        await page.wait_for_timeout(400)

        send_btn, send_selector = await self._first_visible(page, _PROFILE_PANEL_SEND_SELECTORS)
        if send_btn is not None:
            await send_btn.click(force=True)
        else:
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(2500)

        panel = page.locator('[data-e2e="msg-input"]').first
        panel_text = await panel.inner_text() if await panel.count() else ""
        chat_root = page.locator(".componentsRightPanelnotHeaderArea, .componentsRightPanelwrapper").first
        chat_text = await chat_root.inner_text() if await chat_root.count() else ""
        merged = f"{panel_text}\n{chat_text}"
        visible = message in merged
        return {
            "ok": visible,
            "method": "profile_msg_panel",
            "dm_selector": opened.get("selector"),
            "input_selector": input_selector,
            "send_selector": send_selector,
            "verified_in_dialog": visible,
            "text_preview": message[:80],
            "dialog_snippet": merged[:200],
        }

    async def _open_dm_dialog(self, page) -> dict:
        opened = await self._click_dm_button(page)
        if not opened.get("ok"):
            return opened

        try:
            await page.locator('[data-e2e="im-dialog"]').wait_for(state="attached", timeout=15000)
        except Exception:
            return {"ok": False, "error": "im_dialog_not_found", "selector": opened.get("selector")}

        await page.wait_for_timeout(2000)
        return {"ok": True, "selector": opened.get("selector")}

    async def _wait_dm_input(self, page, *, timeout_ms: int = 25000):
        deadline = timeout_ms
        step = 1000
        while deadline > 0:
            inp, selector = await self._first_visible(page, _IM_INPUT_SELECTORS)
            if inp is not None:
                return inp, selector
            await page.wait_for_timeout(step)
            deadline -= step
        return None, None

    @staticmethod
    async def _dialog_hint(page) -> str:
        try:
            dialog = page.locator('[data-e2e="im-dialog"]').first
            if not await dialog.count():
                return ""
            text = await dialog.inner_text()
            for hint in ("无法私信", "互相关注", "隐私", "未开启私信", "加载中"):
                if hint in text:
                    return text[:200]
            return text[:200]
        except Exception:
            return ""

    async def _send_dm_on_profile(self, page, message: str) -> dict:
        opened = await self._click_dm_button(page)
        if not opened.get("ok"):
            return opened

        surface, inp, input_selector = await self._wait_dm_input_surface(page)
        if inp is None or surface is None:
            hint = await self._dialog_hint(page)
            return {
                "ok": False,
                "error": "dm_input_not_found",
                "hint": hint or "点击私信后未出现输入框，可能受隐私/互关限制",
                "dm_selector": opened.get("selector"),
            }

        if surface == "profile_panel":
            return await self._send_via_profile_panel(page, message, inp, input_selector, opened)

        await inp.click()
        await inp.fill(message)
        await page.wait_for_timeout(400)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        dialog = page.locator('[data-e2e="im-dialog"]').first
        dialog_text = await dialog.inner_text() if await dialog.count() else ""
        visible = message in dialog_text
        return {
            "ok": visible,
            "method": "profile_im_dialog",
            "dm_selector": opened.get("selector"),
            "input_selector": input_selector,
            "verified_in_dialog": visible,
            "text_preview": message[:80],
            "dialog_snippet": dialog_text[:200],
        }
