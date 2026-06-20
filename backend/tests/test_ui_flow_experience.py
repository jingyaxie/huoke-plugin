from __future__ import annotations

import json

from app.services.ui_flow.platforms.douyin.experience import DouyinUiFlowExperience


def test_experience_prefer_and_save(tmp_path, monkeypatch):
    class _Settings:
        storage_root = tmp_path

    exp = DouyinUiFlowExperience(_Settings(), tenant_id="default", account_id="default")
    ordered = exp.prefer("SEARCH", "submit", ("enter", "button"))
    assert ordered[0] == "enter"
    exp.record_phase("SEARCH", elapsed_ms=1000, hints={"submit": "button"})
    exp.record_success(keyword="团餐配送", stages=["DONE SEARCH"])
    exp.save()

    exp2 = DouyinUiFlowExperience(_Settings(), tenant_id="default", account_id="default")
    ordered2 = exp2.prefer("SEARCH", "submit", ("enter", "button"))
    assert ordered2[0] == "button"
    assert exp2.data["runs"] == 1
