from app.services.agent_strategy import (
    default_strategy_for_platform,
    list_strategies,
    resolve_agent_strategy,
)
from app.services.agent_strategy.registry import SKILL_FLOW_DOUYIN, STANDALONE_BROWSE_DOUYIN
from app.services.task_skill_playbook import build_allowed_skills


def test_resolve_default_douyin_skill_flow():
    st = resolve_agent_strategy(None, platform="douyin")
    assert st.id == SKILL_FLOW_DOUYIN.id
    assert st.crawl_skill_id == "douyin-keyword-comments"
    assert st.profile_id == "task-douyin-skill-flow"


def test_resolve_standalone_browse_douyin():
    st = resolve_agent_strategy(STANDALONE_BROWSE_DOUYIN.id, platform="douyin")
    assert st.id == STANDALONE_BROWSE_DOUYIN.id
    assert st.inline_ui_outreach is True
    assert st.crawl_skill_id == "standalone-keyword-browse"


def test_resolve_skill_flow_douyin():
    st = resolve_agent_strategy("skill-flow-douyin", platform="douyin")
    assert st.id == SKILL_FLOW_DOUYIN.id
    assert st.crawl_skill_id == "douyin-keyword-comments"
    assert st.execution_mode == "skill_flow"


def test_list_strategies_marks_default():
    items = list_strategies(platform="douyin")
    assert len(items) == 2
    assert {item["id"] for item in items} == {SKILL_FLOW_DOUYIN.id, STANDALONE_BROWSE_DOUYIN.id}
    defaults = [i for i in items if i["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == SKILL_FLOW_DOUYIN.id


def test_playbook_uses_strategy_crawl_skill():
    skill_flow = build_allowed_skills("douyin", strategy=SKILL_FLOW_DOUYIN)
    skill_flow_crawl = next(r for r in skill_flow if r["supervisor_action"] == "crawl_keyword")
    assert skill_flow_crawl["skill_id"] == "douyin-keyword-comments"

    standalone = build_allowed_skills("douyin", strategy=STANDALONE_BROWSE_DOUYIN)
    standalone_crawl = next(r for r in standalone if r["supervisor_action"] == "crawl_keyword")
    assert standalone_crawl["skill_id"] == "standalone-keyword-browse"


def test_default_strategy_xiaohongshu_skill_flow():
    st = default_strategy_for_platform("xiaohongshu")
    assert st.execution_mode == "skill_flow"
