from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.platforms.xiaohongshu import ui_helpers


@pytest.mark.asyncio
async def test_prepare_logged_in_page_skips_dismiss_for_guest():
    page = AsyncMock()
    with patch.object(
        ui_helpers,
        "fetch_user_me",
        new=AsyncMock(return_value={"guest": True, "ok": True}),
    ), patch.object(
        ui_helpers,
        "dismiss_login_overlay",
        new=AsyncMock(return_value={"dismissed": True, "had_modal": True, "actions": ["click"]}),
    ) as dismiss_mock, patch.object(
        ui_helpers,
        "activate_session",
        new=AsyncMock(return_value={"ok": True}),
    ):
        result = await ui_helpers.prepare_logged_in_page(page)

    dismiss_mock.assert_not_called()
    assert result["user_me"]["guest"] is True


@pytest.mark.asyncio
async def test_prepare_logged_in_page_dismisses_when_authenticated():
    page = AsyncMock()
    guest_me = {"guest": False, "ok": True, "user_id": "u1"}
    with patch.object(
        ui_helpers,
        "fetch_user_me",
        new=AsyncMock(return_value=guest_me),
    ), patch.object(
        ui_helpers,
        "dismiss_login_overlay",
        new=AsyncMock(return_value={"dismissed": True, "had_modal": True, "actions": ["escape"]}),
    ) as dismiss_mock, patch.object(
        ui_helpers,
        "activate_session",
        new=AsyncMock(return_value={"ok": True}),
    ):
        result = await ui_helpers.prepare_logged_in_page(page)

    assert dismiss_mock.await_count >= 1
    assert result["user_me"]["guest"] is False
