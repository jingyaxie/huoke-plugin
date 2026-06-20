from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.platforms.douyin.standalone_keyword_browse import (
    PreciseLeadRecord,
    StandaloneKeywordBrowseConfig,
    _flush_unpersisted_leads,
    _persist_lead_immediate,
    _resolve_lead_aweme_id,
)


def _lead(**kwargs) -> PreciseLeadRecord:
    defaults = {
        "comment_id": "7653144046986429221",
        "comment_text": "新手适合吗",
        "username": "test_user",
        "user_id": "uid1",
        "sec_uid": "sec_uid_1",
        "video_url": "https://www.douyin.com/video/7648984993873037541",
        "aweme_id": "",
        "create_time": 1718000000,
        "match_score": 0.85,
        "match_reason": "实操疑问",
        "planned_action": "reply",
    }
    defaults.update(kwargs)
    return PreciseLeadRecord(**defaults)


def test_resolve_lead_aweme_id_from_video_url():
    lead = _lead(aweme_id="")
    assert _resolve_lead_aweme_id(lead) == "7648984993873037541"


def test_persist_lead_immediate_logs_failure_reason():
    db = MagicMock()
    settings = MagicMock()
    config = StandaloneKeywordBrowseConfig(persist_to_db=True, keyword="健身")
    lead = _lead(aweme_id="7648984993873037541")
    phase_log: list[str] = []

    with patch(
        "app.platforms.douyin.standalone_keyword_browse.persist_crawl_skill_result",
        return_value=0,
    ):
        saved = _persist_lead_immediate(
            db_session=db,
            settings=settings,
            tenant_id="default",
            lead=lead,
            config=config,
            phase_log=phase_log,
        )

    assert saved == 0
    assert lead.persisted is False
    assert lead.persist_error
    assert any("PERSIST_FAIL" in line for line in phase_log)


def test_flush_unpersisted_leads_only_pending():
    db = MagicMock()
    settings = MagicMock()
    config = StandaloneKeywordBrowseConfig(persist_to_db=True, keyword="健身")
    done = _lead(comment_id="111", persisted=True, aweme_id="7648984993873037541")
    pending = _lead(comment_id="222", aweme_id="7648984993873037541")
    phase_log: list[str] = []

    with patch(
        "app.platforms.douyin.standalone_keyword_browse.persist_crawl_skill_result",
        return_value=1,
    ) as persist:
        total = _flush_unpersisted_leads(
            db_session=db,
            settings=settings,
            tenant_id="default",
            config=config,
            leads=[done, pending],
            phase_log=phase_log,
        )

    assert total == 1
    assert persist.call_count == 1
    assert pending.persisted is True
    assert any("SALVAGE_FLUSH" in line for line in phase_log)
