"""大量模拟：表单参数 → 独立浏览编排 → 页面阶段门禁 → 是否满足任务要求。"""
from __future__ import annotations

import pytest

from app.platforms.douyin.standalone_keyword_browse import (
    StandaloneKeywordBrowseConfig,
    _decide_outreach_action,
    _keyword_matches_comment,
    _take_unique_comments,
)
from app.schemas.douyin_tools import DouyinStandaloneKeywordBrowseRequest
from tests.standalone_browse_simulator import (
    FORM_REQUIREMENT_KEYS,
    StandaloneVideoRound,
    all_requirements_met,
    config_from_api_request,
    config_from_cli_like,
    evaluate_form_requirements,
    requirement_matrix,
    simulate_standalone_pipeline,
)


def _lead_comment(cid: str, text: str) -> dict:
    return {"comment_id": cid, "comment": text, "username": "u1", "sec_uid": "sec1"}


def _success_round(**kwargs) -> StandaloneVideoRound:
    defaults = {
        "comments": [_lead_comment("c1", "AI获客怎么做")],
        "comment_open_ok": True,
        "feed_visible": True,
        "list_visible": False,
        "after_click_phase": "feed_detail",
    }
    defaults.update(kwargs)
    return StandaloneVideoRound(**defaults)


# ---------------------------------------------------------------------------
# 表单/API/CLI → Config 映射
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        (
            {"keyword": "AI获客", "target_precise_leads": 5, "days": 14},
            {"keyword": "AI获客", "target": 5, "days": 14, "outreach": False},
        ),
        (
            {
                "keyword": "淋浴房",
                "target_precise_leads": 2,
                "execute_outreach": True,
                "test_all_outreach": True,
                "reply_text": "好的",
                "dm_text": "你好",
                "comment_ratio": 40,
                "dm_ratio": 35,
                "follow_ratio": 25,
                "persist_to_db": True,
            },
            {"keyword": "淋浴房", "target": 2, "outreach": True, "persist": True},
        ),
        (
            {
                "keyword": "获客",
                "comment_days": 3,
                "match_keywords": ["引流", "咨询"],
                "exclude_keywords": ["招聘"],
                "max_videos_to_browse": 10,
            },
            {"keyword": "获客", "comment_days": 3, "max_videos": 10},
        ),
    ],
)
def test_api_form_maps_to_config(payload, expected):
    cfg = config_from_api_request(DouyinStandaloneKeywordBrowseRequest.model_validate(payload))
    assert cfg.keyword == expected["keyword"]
    assert cfg.target_precise_leads == expected.get("target", cfg.target_precise_leads)
    if "days" in expected:
        assert cfg.days == expected["days"]
    if "outreach" in expected:
        assert cfg.execute_outreach is expected["outreach"]
    if "persist" in expected:
        assert cfg.persist_to_db is expected["persist"]
    if "comment_days" in expected:
        assert cfg.comment_days == expected["comment_days"]
    if "max_videos" in expected:
        assert cfg.max_videos_to_browse == expected["max_videos"]
    if payload.get("match_keywords"):
        assert cfg.match_keywords == payload["match_keywords"]
    if payload.get("comment_ratio") is not None:
        assert cfg.action_policy["comment_ratio"] == payload["comment_ratio"]


@pytest.mark.parametrize(
    "cli_kwargs,expected",
    [
        ({"keyword": "AI获客", "target_leads": 1, "no_outreach": True}, {"outreach": False, "mk_has_ai": True}),
        (
            {"keyword": "AI获客", "match_keywords": ["获客", "引流"], "no_outreach": False},
            {"outreach": True, "mk": ["获客", "引流"]},
        ),
        ({"keyword": "test", "no_persist": True}, {"persist": False}),
    ],
)
def test_cli_form_maps_to_config(cli_kwargs, expected):
    cfg = config_from_cli_like(**cli_kwargs)
    if "outreach" in expected:
        assert cfg.execute_outreach is expected["outreach"]
        assert cfg.test_all_outreach is expected["outreach"]
    if expected.get("mk_has_ai"):
        assert "AI" in cfg.match_keywords
    if "mk" in expected:
        assert cfg.match_keywords == expected["mk"]
    if "persist" in expected:
        assert cfg.persist_to_db is expected["persist"]


# ---------------------------------------------------------------------------
# 页面阶段门禁（仍在列表 → 禁止开评论/抓评论）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "round_out,should_open_comment",
    [
        (_success_round(), True),
        (
            _success_round(
                list_visible=True,
                feed_visible=False,
                after_click_phase="search_list",
            ),
            False,
        ),
        (
            _success_round(
                feed_ready=False,
                after_click_phase="feed_detail",
            ),
            False,
        ),
        (
            StandaloneVideoRound(
                click_ok=False,
                after_click_phase="search_list",
                list_visible=True,
            ),
            False,
        ),
        (
            _success_round(after_click_phase="video_page", feed_visible=True),
            True,
        ),
    ],
)
def test_page_phase_blocks_comment_when_still_on_list(round_out, should_open_comment):
    cfg = config_from_cli_like(keyword="AI获客", target_leads=1)
    trace = simulate_standalone_pipeline(cfg, [round_out])
    opened = any("COMMENT_OPEN ok=True" in s for s in trace.steps)
    blocked = any("仍在搜索列表" in s for s in trace.steps)
    if should_open_comment:
        assert opened
        assert trace.videos_entered_feed == 1
    else:
        assert not opened or blocked or trace.videos_entered_feed == 0


@pytest.mark.parametrize(
    "url,feed_visible,list_visible,expected_phase",
    [
        ("https://www.douyin.com/jingxuan/search/kw?type=general", False, True, "search_list"),
        ("https://www.douyin.com/jingxuan/search/kw?modal_id=7123456789", False, True, "search_list"),
        ("https://www.douyin.com/jingxuan/search/kw?modal_id=7123456789", True, False, "feed_detail"),
        ("https://www.douyin.com/video/7123456789012345678", False, False, "video_page"),
    ],
)
@pytest.mark.asyncio
async def test_classify_douyin_page_url_dom_matrix(
    monkeypatch,
    url,
    feed_visible,
    list_visible,
    expected_phase,
):
    from app.services.ui_flow.platforms.douyin import feed_ui

    class _Page:
        def __init__(self, u: str):
            self.url = u

        def locator(self, _sel):
            return self

        async def count(self):
            return 1 if list_visible else 0

    async def _feed(_page):
        return feed_visible

    async def _list(_page):
        return list_visible

    monkeypatch.setattr(feed_ui, "feed_overlay_visible", _feed)
    monkeypatch.setattr(feed_ui, "search_list_visible", _list)

    snap = await feed_ui.classify_douyin_page(_Page(url))
    assert snap["phase"] == expected_phase


# ---------------------------------------------------------------------------
# 编排链路：搜索 → 点击 → 评论 → 线索 → 触达
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target_leads,rounds,expect_reached,expect_leads",
    [
        (1, [_success_round()], True, 1),
        (2, [_success_round(comments=[_lead_comment("a", "怎么获客")])], False, 1),
        (
            2,
            [
                _success_round(comments=[_lead_comment("a", "AI获客教程")]),
                _success_round(comments=[_lead_comment("b", "引流方案咨询")]),
            ],
            True,
            2,
        ),
        (
            1,
            [
                StandaloneVideoRound(click_ok=False),
                _success_round(),
            ],
            True,
            1,
        ),
        (
            1,
            [
                _success_round(list_visible=True, feed_visible=False, after_click_phase="search_list"),
                _success_round(),
            ],
            True,
            1,
        ),
    ],
)
def test_pipeline_target_leads_stop(target_leads, rounds, expect_reached, expect_leads):
    cfg = config_from_cli_like(keyword="AI获客", target_leads=target_leads, match_keywords=["获客", "引流", "AI"])
    trace = simulate_standalone_pipeline(cfg, rounds)
    assert trace.target_reached is expect_reached
    assert len(trace.precise_leads) == expect_leads


def test_pipeline_respects_max_videos_cap():
    cfg = config_from_cli_like(keyword="AI获客", target_leads=1, max_videos=2)
    rounds = [_success_round(comments=[]) for _ in range(5)]
    trace = simulate_standalone_pipeline(cfg, rounds)
    assert trace.videos_attempted == 2
    assert not trace.target_reached


def test_pipeline_dedupes_comments_across_videos():
    cfg = config_from_cli_like(keyword="AI获客", target_leads=3, match_keywords=["获客"])
    dup = _lead_comment("same", "怎么获客")
    trace = simulate_standalone_pipeline(
        cfg,
        [
            _success_round(comments=[dup]),
            _success_round(comments=[dup, _lead_comment("b", "获客工具")]),
        ],
    )
    assert trace.duplicates_skipped >= 1
    assert len(trace.precise_leads) == 2


@pytest.mark.parametrize("execute_outreach,test_all,expect_actions", [
    (False, False, 0),
    (True, True, 3),
    (True, False, 1),
])
def test_pipeline_outreach_follows_form_toggle(execute_outreach, test_all, expect_actions):
    cfg = StandaloneKeywordBrowseConfig(
        keyword="AI获客",
        target_precise_leads=1,
        match_keywords=["获客"],
        execute_outreach=execute_outreach,
        test_all_outreach=test_all,
        reply_text="同意",
        dm_text="hi",
    )
    trace = simulate_standalone_pipeline(cfg, [_success_round()])
    if expect_actions == 0:
        assert trace.outreach_actions == []
    elif expect_actions == 3:
        assert trace.outreach_actions == ["reply", "follow", "dm"]
    else:
        assert len(trace.outreach_actions) == 1


# ---------------------------------------------------------------------------
# 表单要求满足度矩阵（大量条件组合）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "form_case",
    [
        {"keyword": "AI获客", "target_leads": 1, "days": 7},
        {"keyword": "淋浴房", "target_leads": 3, "days": 14, "comment_days": 5},
        {"keyword": "获客", "target_leads": 2, "match_keywords": ["引流", "咨询"], "exclude_keywords": ["招聘"]},
        {"keyword": "AI", "target_leads": 1, "no_outreach": False, "reply_text": "好", "dm_text": "hi"},
        {"keyword": "test", "target_leads": 1, "no_outreach": True},
        {"keyword": "AI获客", "target_leads": 1, "max_videos": 3},
        {"keyword": "AI获客", "target_leads": 1, "no_persist": True},
    ],
)
def test_form_requirements_satisfied_for_happy_path(form_case):
    cfg = config_from_cli_like(**form_case)
    n = max(1, int(cfg.target_precise_leads))

    def _round(i: int) -> StandaloneVideoRound:
        return _success_round(comments=[_lead_comment(f"c{i}", f"AI获客咨询{i}")])

    trace = simulate_standalone_pipeline(cfg, [_round(i) for i in range(n)])
    checks = evaluate_form_requirements(cfg, trace)
    assert all_requirements_met(checks), checks


def test_requirement_matrix_batch():
    configs = [
        config_from_cli_like(keyword="AI获客", target_leads=1),
        config_from_api_request(
            DouyinStandaloneKeywordBrowseRequest.model_validate(
                {
                    "keyword": "淋浴房",
                    "target_precise_leads": 2,
                    "execute_outreach": True,
                    "reply_text": "好的",
                    "dm_text": "你好",
                }
            )
        ),
    ]

    def _rounds(cfg):
        n = max(1, int(cfg.target_precise_leads))
        return [
            _success_round(comments=[_lead_comment(f"c{i}", f"AI获客咨询{i}")])
            for i in range(n)
        ]

    rows = requirement_matrix(configs, _rounds)
    assert len(rows) == 2
    assert all(r["ok"] for r in rows)


# ---------------------------------------------------------------------------
# 关键词匹配 / 触达策略（表单 match_keywords、action_policy）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,match,exclude,expected",
    [
        ("AI获客怎么做", ["获客", "AI"], [], True),
        ("招聘销售", ["获客"], ["招聘"], False),
        ("引流方案多少钱", ["引流", "多少钱"], [], True),
        ("hi", ["获客"], [], False),
    ],
)
def test_keyword_match_matrix(text, match, exclude, expected):
    cfg = StandaloneKeywordBrowseConfig(
        keyword="AI获客",
        match_keywords=match,
        exclude_keywords=exclude,
        min_comment_length=2,
    )
    assert _keyword_matches_comment(cfg, text) is expected


@pytest.mark.asyncio
async def test_outreach_action_respects_policy_caps():
    cfg = StandaloneKeywordBrowseConfig(
        keyword="k",
        action_policy={
            "comment_ratio": 100,
            "dm_ratio": 0,
            "follow_ratio": 0,
            "max_replies": 1,
            "max_dms": 0,
            "max_follows": 0,
        },
    )
    stats = {"replies": 1, "dms": 0, "follows": 0}
    action = await _decide_outreach_action(cfg, stats)
    assert action in {"dm", "follow", "skip"}


# ---------------------------------------------------------------------------
# 失败场景：modal_id 假阳性 / 列表滑动不进入详情（回归用例）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure_rounds,expect_feed_entries,expect_leads",
    [
        (
            [
                StandaloneVideoRound(
                    click_ok=True,
                    after_click_phase="search_list",
                    feed_visible=False,
                    list_visible=True,
                    feed_ready=False,
                )
            ],
            0,
            0,
        ),
        (
            [
                StandaloneVideoRound(
                    click_ok=True,
                    after_click_phase="search_list",
                    feed_visible=False,
                    list_visible=True,
                ),
                _success_round(),
            ],
            1,
            1,
        ),
        (
            [
                StandaloneVideoRound(click_ok=True, comment_open_ok=False, feed_visible=True),
            ],
            1,
            0,
        ),
    ],
)
def test_regression_stuck_on_search_list(failure_rounds, expect_feed_entries, expect_leads):
    """模拟：URL 有 modal_id 但 DOM 仍在列表 → 不应抓评论/出线索。"""
    cfg = config_from_cli_like(keyword="AI获客", target_leads=1)
    trace = simulate_standalone_pipeline(cfg, failure_rounds)
    assert trace.videos_entered_feed == expect_feed_entries
    assert len(trace.precise_leads) == expect_leads


def test_all_form_requirement_keys_documented():
    checks = evaluate_form_requirements(
        config_from_cli_like(keyword="AI获客", target_leads=1),
        simulate_standalone_pipeline(
            config_from_cli_like(keyword="AI获客", target_leads=1),
            [_success_round()],
        ),
    )
    assert set(checks.keys()) == set(FORM_REQUIREMENT_KEYS)
