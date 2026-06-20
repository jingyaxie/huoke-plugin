from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platforms.douyin.human_guards import HumanBrowseGuardError
from app.platforms.douyin.standalone_keyword_browse import (
    PreciseLeadRecord,
    StandaloneKeywordBrowseConfig,
    _execute_outreach_if_needed,
    _run_lead_outreach_safe,
)


def _lead(**kwargs) -> PreciseLeadRecord:
    defaults = {
        "comment_id": "7653144046986429221",
        "comment_text": "新手适合吗",
        "username": "test_user",
        "user_id": "uid1",
        "sec_uid": "sec_uid_1",
        "video_url": "https://www.douyin.com/video/7648984993873037541",
        "aweme_id": "7648984993873037541",
        "create_time": 1718000000,
        "match_score": 0.85,
        "match_reason": "实操疑问",
        "planned_action": "follow",
    }
    defaults.update(kwargs)
    return PreciseLeadRecord(**defaults)


@pytest.mark.asyncio
async def test_execute_outreach_follow_fallback_to_reply_does_not_crash():
    """follow 打开主页失败时回退 reply，不应触发 human_reply_comment UnboundLocalError。"""
    page = MagicMock()
    settings = MagicMock()
    config = StandaloneKeywordBrowseConfig(
        execute_outreach=True,
        reply_text="您好，看到您咨询健身",
        dm_text="私信模板",
    )
    lead = _lead(planned_action="follow")

    with patch(
        "app.services.social_roam.human.douyin.warm_outreach_profile.warm_outreach_follow_dm_from_comment",
        new_callable=AsyncMock,
        return_value={
            "ok": False,
            "error": "关注失败",
            "follow": {"ok": False, "error": "未打开主页"},
        },
    ) as warm_outreach, patch(
        "app.services.social_roam.human.douyin.actions.human_reply_comment",
        new_callable=AsyncMock,
        return_value={"ok": True, "capture_method": "douyin_comment_ui_human"},
    ) as reply:
        result = await _execute_outreach_if_needed(
            page,
            settings,
            tenant_id="default",
            account_id="default",
            action="follow",
            lead=lead,
            config=config,
        )

    warm_outreach.assert_awaited_once()
    reply.assert_awaited_once()
    assert result.get("ok") is True
    assert result.get("action") == "reply"
    assert result.get("fallback_from") == "follow"


@pytest.mark.asyncio
async def test_execute_outreach_dm_fallback_to_reply_when_profile_open_fails():
    page = MagicMock()
    settings = MagicMock()
    config = StandaloneKeywordBrowseConfig(
        execute_outreach=True,
        reply_text="回复模板",
        dm_text="私信模板",
    )
    lead = _lead(planned_action="dm")

    with patch(
        "app.services.social_roam.human.douyin.warm_outreach_profile.warm_outreach_follow_dm_from_comment",
        new_callable=AsyncMock,
        return_value={
            "ok": False,
            "error": "私信失败",
            "dm": {"ok": False, "error": "profile_missing"},
        },
    ), patch(
        "app.services.social_roam.human.douyin.actions.human_reply_comment",
        new_callable=AsyncMock,
        return_value={"ok": False, "error": "未找到回复按钮"},
    ) as reply:
        result = await _execute_outreach_if_needed(
            page,
            settings,
            tenant_id="default",
            account_id="default",
            action="dm",
            lead=lead,
            config=config,
        )

    reply.assert_awaited_once()
    assert result.get("ok") is False
    assert result.get("action") == "dm"


@pytest.mark.asyncio
async def test_run_lead_outreach_safe_contains_guard_error():
    page = MagicMock()
    settings = MagicMock()
    config = StandaloneKeywordBrowseConfig(
        execute_outreach=True,
        reply_text="回复模板",
    )
    lead = _lead(planned_action="reply")

    with patch(
        "app.platforms.douyin.standalone_keyword_browse._execute_outreach_if_needed",
        new_callable=AsyncMock,
        side_effect=HumanBrowseGuardError("未检测到抖音登录 Cookie"),
    ):
        result = await _run_lead_outreach_safe(
            page,
            settings,
            tenant_id="default",
            account_id="default",
            action="reply",
            lead=lead,
            config=config,
        )

    assert result.get("ok") is False
    assert result.get("guard") is True
    assert "Cookie" in str(result.get("error") or "")
