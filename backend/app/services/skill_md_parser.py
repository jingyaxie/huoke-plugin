from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.skill import SkillAction, SkillCreate, SkillParameter, SkillType

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", re.DOTALL)
JSON_BLOCK_RE = re.compile(r"```(?:json)?\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

BROWSER_TOOLS = {
    "browser_goto",
    "browser_click",
    "browser_fill",
    "browser_press",
    "browser_scroll",
    "browser_wait",
    "browser_get_text",
    "browser_get_page_info",
    "browser_screenshot",
}


def _parse_frontmatter_lines(block: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data


def _extract_json_section(body: str, heading: str) -> Any | None:
    pattern = re.compile(
        rf"##\s+{re.escape(heading)}\s*\n+(```(?:json)?\r?\n(.*?)```)",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(body)
    if not match:
        return None
    raw = match.group(2).strip()
    if not raw:
        return None
    return json.loads(raw)


def _strip_sections(body: str) -> str:
    cleaned = re.sub(
        r"##\s+(Parameters|Actions)\s*\n+```(?:json)?\r?\n.*?```",
        "",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = H1_RE.sub("", cleaned, count=1)
    return cleaned.strip()


def _display_name(body: str, skill_id: str) -> str:
    match = H1_RE.search(body)
    if match:
        return match.group(1).strip()
    return skill_id.replace("-", " ").replace("_", " ").title()


def parse_skill_md(content: str) -> SkillCreate:
    text = content.strip()
    if not text:
        raise ValueError("SKILL.md 内容为空")

    meta: dict[str, str] = {}
    body = text
    match = FRONTMATTER_RE.match(text)
    if match:
        meta = _parse_frontmatter_lines(match.group(1))
        body = match.group(2)

    skill_id = (meta.get("name") or meta.get("id") or "").strip()
    if not skill_id:
        raise ValueError("SKILL.md 缺少 frontmatter 字段 name（技能 ID）")

    description = (meta.get("description") or "").strip()
    if not description:
        raise ValueError("SKILL.md 缺少 frontmatter 字段 description")

    skill_type: SkillType = meta.get("type", "instruction")  # type: ignore[assignment]
    if skill_type not in {"instruction", "actions", "builtin"}:
        raise ValueError(f"不支持的技能类型: {skill_type}")

    enabled_raw = meta.get("enabled", "true").lower()
    enabled = enabled_raw not in {"false", "0", "no"}
    manual_raw = meta.get("disable-model-invocation", meta.get("disable_model_invocation", "false")).lower()
    disable_model_invocation = manual_raw in {"true", "1", "yes"}

    parameters_raw = _extract_json_section(body, "Parameters")
    actions_raw = _extract_json_section(body, "Actions")
    parameters = [SkillParameter.model_validate(item) for item in (parameters_raw or [])]
    actions = [SkillAction.model_validate(item) for item in (actions_raw or [])]

    instruction_body = _strip_sections(body)
    display = _display_name(body, skill_id)
    title_override = meta.get("title", "").strip()
    name = title_override or display

    builtin_handler = meta.get("builtin_handler")
    if builtin_handler in {"", "null", "none"}:
        builtin_handler = None

    if skill_type == "actions" and not actions:
        raise ValueError("actions 类型技能需要 ## Actions JSON 代码块")
    if skill_type == "instruction" and not instruction_body and not actions:
        raise ValueError("instruction 类型技能需要正文指令内容")
    if skill_type == "builtin" and not builtin_handler:
        raise ValueError("builtin 类型技能需要 frontmatter 字段 builtin_handler")

    return SkillCreate(
        id=skill_id,
        name=name,
        description=description,
        type=skill_type,
        enabled=enabled,
        disable_model_invocation=disable_model_invocation,
        parameters=parameters,
        content=instruction_body,
        actions=actions,
        builtin_handler=builtin_handler,
    )


def render_skill_md(skill: dict[str, Any]) -> str:
    skill_id = skill["id"]
    name = skill.get("name") or skill_id
    description = skill.get("description") or ""
    skill_type = skill.get("type") or "instruction"
    enabled = skill.get("enabled", True)
    disable_model_invocation = skill.get("disable_model_invocation", False)
    parameters = skill.get("parameters") or []
    actions = skill.get("actions") or []
    content = skill.get("content") or ""
    builtin_handler = skill.get("builtin_handler")

    lines = [
        "---",
        f"name: {skill_id}",
        f"description: {description}",
        f"type: {skill_type}",
        f"enabled: {str(enabled).lower()}",
    ]
    if disable_model_invocation:
        lines.append("disable-model-invocation: true")
    if builtin_handler:
        lines.append(f"builtin_handler: {builtin_handler}")
    lines.extend(["---", "", f"# {name}", ""])

    if content.strip():
        lines.append(content.strip())
        lines.append("")

    if parameters:
        lines.extend(
            [
                "## Parameters",
                "",
                "```json",
                json.dumps(parameters, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )

    if actions:
        lines.extend(
            [
                "## Actions",
                "",
                "```json",
                json.dumps(actions, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def extract_actions_from_steps(steps: list[dict[str, Any]]) -> list[SkillAction]:
    actions: list[SkillAction] = []
    for step in steps:
        tool = step.get("tool") or step.get("name")
        if not tool or tool not in BROWSER_TOOLS:
            continue
        args = step.get("arguments") or step.get("args") or {}
        if step.get("status") == "error" or step.get("result", {}).get("error"):
            continue
        actions.append(SkillAction(tool=tool, args=dict(args)))
    if not actions:
        raise ValueError("未找到可录制的 browser_* 操作步骤")
    return actions
