from __future__ import annotations

from app.services.ui_flow.step_overlay import (
    OVERLAY_ELEMENT_ID,
    OVERLAY_TITLE,
    _SET_STEP_OVERLAY_JS,
)


def test_overlay_constants():
    assert OVERLAY_ELEMENT_ID == "__huoke_step_overlay__"
    assert OVERLAY_TITLE == "Huoke"
    assert OVERLAY_ELEMENT_ID in _SET_STEP_OVERLAY_JS
    assert "pointerEvents" in _SET_STEP_OVERLAY_JS
    assert "2147483646" in _SET_STEP_OVERLAY_JS
    assert "__detail" in _SET_STEP_OVERLAY_JS
