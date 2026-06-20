from __future__ import annotations

import json
from pathlib import Path

from app.core.antibot import _BLOCKED_PROTOCOL_SCHEMES, seed_profile_protocol_prefs


def test_seed_profile_protocol_prefs_writes_local_state_and_preferences(tmp_path: Path) -> None:
    seed_profile_protocol_prefs(tmp_path)
    local_state = json.loads((tmp_path / "Local State").read_text(encoding="utf-8"))
    prefs = json.loads((tmp_path / "Default" / "Preferences").read_text(encoding="utf-8"))

    excluded = local_state["protocol_handler"]["excluded_schemes"]
    assert excluded["douyin"] is True
    assert excluded["snssdk1128"] is True
    assert excluded["kwai"] is True

    pref_excluded = prefs["protocol_handler"]["excluded_schemes"]
    assert pref_excluded["douyin"] is True
    assert prefs["custom_handlers"]["enabled"] is False
    assert len(pref_excluded) >= len(_BLOCKED_PROTOCOL_SCHEMES)


def test_is_external_protocol_url() -> None:
    from app.core.antibot import _is_external_protocol_url

    assert _is_external_protocol_url("douyin://open") is True
    assert _is_external_protocol_url("https://www.douyin.com/hot") is False
    assert _is_external_protocol_url("snssdk1128://feed") is True
