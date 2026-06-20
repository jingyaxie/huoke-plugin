from __future__ import annotations

from app.services.skill_failure import classify_skill_failure, is_recoverable_failure, is_terminal_failure


def test_classify_login_failure():
    assert classify_skill_failure({"error": "需要登录 cookie"}) == "login_required"
    assert is_terminal_failure("login_required")


def test_classify_empty_data():
    assert classify_skill_failure({"error": "未搜索到视频"}) == "empty_data"
    assert is_recoverable_failure("empty_data")


def test_success_has_no_failure():
    assert classify_skill_failure({"status": "completed", "summary": "ok"}) is None
