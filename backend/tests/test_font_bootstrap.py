from __future__ import annotations

import pytest

from app.services.font_bootstrap import count_zh_font_families, ensure_cjk_fonts


@pytest.mark.asyncio
async def test_ensure_cjk_fonts_skip_when_present():
    count = count_zh_font_families()
    if count <= 0:
        pytest.skip("no fc-list or no zh fonts in CI/dev environment")
    result = await ensure_cjk_fonts()
    assert result["action"] == "skip"
    assert result["ready"] is True


def test_count_zh_font_families_returns_int():
    value = count_zh_font_families()
    assert isinstance(value, int)
