from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


class MockLocator:
    """Minimal Playwright locator stub for xhs human-flow tests."""

    def __init__(
        self,
        *,
        count: int = 1,
        visible: bool = True,
        inner_text: str = "关注",
        click_ok: bool = True,
    ) -> None:
        self._count = count
        self._visible = visible
        self._inner_text = inner_text
        self._click_ok = click_ok
        self.first = self

    async def count(self) -> int:
        return self._count

    async def is_visible(self) -> bool:
        return self._visible and self._count > 0

    async def inner_text(self) -> str:
        return self._inner_text

    async def click(self, *args, **kwargs) -> None:
        if not self._click_ok:
            raise RuntimeError("click failed")

    async def fill(self, *args, **kwargs) -> None:
        return None

    async def scroll_into_view_if_needed(self, *args, **kwargs) -> None:
        return None

    def locator(self, *args, **kwargs) -> MockLocator:
        return self


def make_mock_page(
    *,
    url: str = "https://www.xiaohongshu.com/explore/note123",
    title: str = "测试笔记",
    body_text: str = "关注",
    locator: MockLocator | None = None,
) -> MagicMock:
    page = MagicMock()
    page.url = url
    page.title = AsyncMock(return_value=title)
    page.evaluate = AsyncMock(return_value=body_text)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.goto = AsyncMock(return_value=None)
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock(return_value=None)
    page.mouse.wheel = AsyncMock(return_value=None)
    page.viewport_size = {"width": 1440, "height": 900}
    page.locator = MagicMock(return_value=locator or MockLocator())
    page.route = AsyncMock(return_value=None)
    page.unroute = AsyncMock(return_value=None)
    page.on = MagicMock()
    page.remove_listener = MagicMock()
    page.context = MagicMock()
    return page


class FakeXhsSessionStore:
    def is_usable(self, tenant_id: str, account_id: str = "default") -> bool:
        return True

    def load(self, tenant_id: str, account_id: str = "default"):
        return {"cookies": [{"name": "web_session", "value": "x"}]}

    def is_ready(self, state) -> bool:
        return True

    def login_status(self, tenant_id: str, account_id: str = "default"):
        return {"status": "ready", "cookie_ready": True}
