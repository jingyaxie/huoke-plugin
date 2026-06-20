from app.services.agent_strategy.registry import SKILL_FLOW_DOUYIN
from app.services.task_brief_service import _fallback_brief, _finalize_brief, TaskBrief
from app.services.task_skill_playbook import (
    ACTION_TO_SKILL,
    attach_skill_playbook_to_brief_md,
    build_allowed_skills,
    build_skill_playbook_md,
    skill_id_for_supervisor_action,
)


def test_build_allowed_skills_has_crawl_and_outreach():
    skills = build_allowed_skills("douyin")
    actions = {row["supervisor_action"] for row in skills}
    assert "crawl_keyword" in actions
    assert "reply" in actions
    assert "query_stats" in actions
    crawl = next(r for r in skills if r["supervisor_action"] == "crawl_keyword")
    assert crawl["skill_id"] == "douyin-keyword-comments"


def test_skill_playbook_md_lists_bindings():
    md = build_skill_playbook_md("douyin")
    assert "## Skill 白名单" in md
    assert "douyin-keyword-comments" in md
    assert "reply-comment" in md
    assert "禁止 LLM 手工搜索" in md
    assert "禁止" in md


def test_fallback_brief_includes_skill_playbook():
    brief = _fallback_brief("抖音关键词团餐配送，目标50条")
    assert "## Skill 白名单" in brief.brief_md
    assert len(brief.allowed_skills) >= 6
    assert brief.allowed_skills[0]["skill_id"]


def test_finalize_brief_attaches_playbook():
    brief = _finalize_brief(TaskBrief(title="测试", platform="douyin", brief_md="# 测试\n\n## 目标\n抓取"))
    assert "douyin-keyword-comments" in brief.brief_md
    assert ACTION_TO_SKILL["reply"] == "reply-comment"


def test_build_allowed_skills_skill_flow():
    skills = build_allowed_skills("douyin", strategy=SKILL_FLOW_DOUYIN)
    crawl = next(r for r in skills if r["supervisor_action"] == "crawl_keyword")
    assert crawl["skill_id"] == "douyin-keyword-comments"


def test_finalize_brief_skill_flow_strategy():
    brief = _finalize_brief(
        TaskBrief(title="测试", platform="douyin", brief_md="# 测试"),
        agent_strategy=SKILL_FLOW_DOUYIN.id,
    )
    assert brief.agent_strategy == SKILL_FLOW_DOUYIN.id
    assert "douyin-keyword-comments" in brief.brief_md
    crawl = next(r for r in brief.allowed_skills if r["supervisor_action"] == "crawl_keyword")
    assert crawl["skill_id"] == "douyin-keyword-comments"


def test_finalize_brief_skill_flow_plan_driven():
    brief = _finalize_brief(
        TaskBrief(title="测试", platform="douyin", brief_md="# 测试"),
        agent_strategy=SKILL_FLOW_DOUYIN.id,
    )
    assert brief.agent_strategy == SKILL_FLOW_DOUYIN.id
    assert brief.goals.get("supervisor_plan_only") is True
    crawl = next(r for r in brief.allowed_skills if r["supervisor_action"] == "crawl_keyword")
    assert crawl["skill_id"] == "douyin-keyword-comments"


def test_fallback_brief_with_strategy_in_json():
    msg = '{"keyword":"团餐","platform":"douyin","agent_strategy":"skill-flow-douyin"}'
    brief = _fallback_brief(msg)
    assert brief.agent_strategy == SKILL_FLOW_DOUYIN.id
    crawl = next(r for r in brief.allowed_skills if r["supervisor_action"] == "crawl_keyword")
    assert crawl["skill_id"] == "douyin-keyword-comments"


def test_attach_replaces_existing_playbook_section():
    old = "# T\n\n## Skill 白名单\n旧内容\n\n## 其他"
    new = attach_skill_playbook_to_brief_md(old, "douyin", strategy=SKILL_FLOW_DOUYIN)
    assert "旧内容" not in new
    assert "reply-comment" in new
