from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from playwright.async_api import BrowserContext, ConsoleMessage, Page

logger = logging.getLogger(__name__)

_TAB_AUDIT_ATTR = "_huoke_tab_audit_events"
_TAB_AUDIT_BRIDGE_INSTALLED = "_huoke_tab_audit_bridge_installed"
_TAB_AUDIT_MAX = 300
AUDIT_CONSOLE_PREFIX = "__HUOKE_TAB_AUDIT__"


def tab_audit_enabled() -> bool:
    """默认开启，便于排查 tab 闪动；设 HUOKE_TAB_AUDIT=0 可关。"""
    import os

    return os.environ.get("HUOKE_TAB_AUDIT", "1").strip().lower() not in {"0", "false", "no", "off"}


def record_tab_audit(
    context: BrowserContext,
    event: str,
    *,
    source: str = "",
    action: str = "",
    url: str = "",
    **extra: Any,
) -> None:
    if not tab_audit_enabled():
        return
    row: dict[str, Any] = {
        "ts": round(time.time(), 3),
        "event": event,
        "source": source,
        "action": action,
        "url": url,
    }
    row.update({k: v for k, v in extra.items() if v is not None})
    events: list[dict[str, Any]] = getattr(context, _TAB_AUDIT_ATTR, None) or []
    events.append(row)
    if len(events) > _TAB_AUDIT_MAX:
        del events[: len(events) - _TAB_AUDIT_MAX]
    setattr(context, _TAB_AUDIT_ATTR, events)
    logger.warning("TAB_AUDIT %s", json.dumps(row, ensure_ascii=False))


def get_tab_audit_events(context: BrowserContext | None) -> list[dict[str, Any]]:
    if context is None:
        return []
    return list(getattr(context, _TAB_AUDIT_ATTR, None) or [])


def clear_tab_audit(context: BrowserContext) -> None:
    setattr(context, _TAB_AUDIT_ATTR, [])


def _parse_console_audit(text: str) -> dict[str, Any] | None:
    if AUDIT_CONSOLE_PREFIX not in text:
        return None
    raw = text.split(AUDIT_CONSOLE_PREFIX, 1)[1].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _on_page_console(context: BrowserContext, msg: ConsoleMessage) -> None:
    payload = _parse_console_audit(msg.text)
    if not payload:
        return
    record_tab_audit(
        context,
        str(payload.get("event") or "window.open"),
        source="window.open.js",
        action=str(payload.get("action") or ""),
        url=str(payload.get("url") or ""),
        page_url=str(payload.get("page_url") or ""),
        blocked=bool(payload.get("blocked")),
        tracking=bool(payload.get("tracking")),
        stack=str(payload.get("stack") or "")[:800],
        target=str(payload.get("target") or ""),
    )


async def _attach_console_audit(page: Page, context: BrowserContext) -> None:
    if page.is_closed():
        return

    def handler(msg: ConsoleMessage) -> None:
        _on_page_console(context, msg)

    page.on("console", handler)


async def install_tab_audit_bridge(context: BrowserContext, main_page: Page | None = None) -> None:
    """监听 page 事件与 console，汇总 tab 审计日志。"""
    if not tab_audit_enabled() or getattr(context, _TAB_AUDIT_BRIDGE_INSTALLED, False):
        return

    from app.core.antibot import _MAIN_PAGE_HOLDER

    def _on_new_page(page: Page) -> None:
        holder: dict[str, Page | None] = getattr(context, _MAIN_PAGE_HOLDER, None) or {}
        main = holder.get("page")
        is_main = page is main
        try:
            asyncio.get_running_loop().create_task(_audit_new_page(context, page, is_main=is_main))
            asyncio.get_running_loop().create_task(_attach_console_audit(page, context))
        except RuntimeError:
            pass

    context.on("page", _on_new_page)
    if main_page is not None:
        await _attach_console_audit(main_page, context)
    setattr(context, _TAB_AUDIT_BRIDGE_INSTALLED, True)
    record_tab_audit(context, "audit_bridge_ready", source="popup_tab_audit", action="install")


async def _audit_new_page(context: BrowserContext, page: Page, *, is_main: bool) -> None:
    url0 = (page.url or "").strip()
    opener = None
    with contextlib.suppress(Exception):
        opener_page = page.opener
        if opener_page is not None:
            opener = (opener_page.url or "").strip()
    record_tab_audit(
        context,
        "page_created",
        source="playwright.context.on_page",
        url=url0,
        is_main=is_main,
        opener_url=opener,
    )
    await asyncio.sleep(0.08)
    if page.is_closed():
        record_tab_audit(
            context,
            "page_closed_quick",
            source="playwright",
            action="observed",
            url=url0,
            is_main=is_main,
            note="page closed within 80ms of creation",
        )
        return
    url1 = (page.url or "").strip()
    if url1 != url0:
        record_tab_audit(
            context,
            "page_url_changed",
            source="playwright",
            action="navigate",
            url=url1,
            from_url=url0,
            is_main=is_main,
        )
