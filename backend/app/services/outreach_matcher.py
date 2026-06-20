from __future__ import annotations

import re
from typing import Any


def match_spec(text: str, spec: dict[str, Any] | None) -> tuple[bool, str]:
    if not spec:
        return False, "empty_spec"
    mode = str(spec.get("mode") or "keyword").strip().lower()
    if mode == "never":
        return False, "never"
    normalized = (text or "").strip()
    min_len = int(spec.get("min_comment_length") or 0)
    if len(normalized) < min_len:
        return False, "too_short"
    for word in spec.get("exclude_keywords") or []:
        if word and str(word) in normalized:
            return False, f"exclude:{word}"
    if mode == "regex":
        pattern = str(spec.get("pattern") or "").strip()
        if pattern and re.search(pattern, normalized):
            return True, f"regex:{pattern}"
        return False, "regex_miss"
    keywords = [str(k).strip() for k in (spec.get("keywords") or []) if str(k).strip()]
    for kw in keywords:
        if kw in normalized:
            return True, f"keyword:{kw}"
    return False, "no_match"


def resolve_follow_match(
    comment_text: str,
    comment_match: dict[str, Any],
    follow_match: dict[str, Any] | None,
) -> tuple[bool, str]:
    if not follow_match:
        return match_spec(comment_text, comment_match)
    mode = str(follow_match.get("mode") or "").strip().lower()
    if mode == "never":
        return False, "never"
    if mode in {"same_as_comment", "same"}:
        return match_spec(comment_text, comment_match)
    return match_spec(comment_text, follow_match)


def action_enabled(actions: list[dict[str, Any]], action_type: str) -> bool:
    return any(str(item.get("type") or "").strip().lower() == action_type for item in actions)


def reply_template(actions: list[dict[str, Any]]) -> str:
    for item in actions:
        if str(item.get("type") or "").strip().lower() == "reply":
            return str(item.get("template") or "您好～").strip()
    return "您好～"


def render_template(template: str, *, nickname: str, comment: str) -> str:
    text = template or ""
    text = text.replace("{{username}}", nickname).replace("{{nickname}}", nickname)
    text = text.replace("{{comment}}", comment)
    return text.strip()
