from __future__ import annotations

from typing import Any


def build_validation_report(
    *,
    status: str,
    summary: str,
    task_snapshot: dict[str, Any],
    review_report: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    suggestions: list[str] = []

    has_key_evidence = bool(
        task_snapshot.get("aweme_id")
        or task_snapshot.get("video_id")
        or task_snapshot.get("video_url")
        or task_snapshot.get("videos_preview")
    )
    total_tools = int(review_report.get("total_tools") or 0)
    top_failures = review_report.get("top_failures") or []

    score = 90
    if status != "completed":
        score -= 30
        issues.append("任务未完成")
    if not has_key_evidence:
        score -= 20
        issues.append("缺少关键结构化证据（aweme_id/video_url）")
        suggestions.append("优先调用接口抓取并沉淀 task_snapshot 后再执行提取链路")
    if total_tools > 40:
        score -= 10
        issues.append(f"工具调用偏多（{total_tools}）")
        suggestions.append("减少重复搜索，优先复用已有证据")
    if top_failures:
        issues.append("存在失败类型：" + ", ".join(str(i.get("type")) for i in top_failures[:3]))
        suggestions.append("先按失败类型执行恢复策略，再继续主流程")
    if summary.strip() == "":
        score -= 10
        issues.append("缺少清晰总结")
        suggestions.append("补充可交付摘要，明确结果与限制")

    score = max(0, min(100, score))
    level = "high" if score >= 85 else "medium" if score >= 65 else "low"
    return {
        "score": score,
        "confidence": level,
        "issues": issues,
        "suggestions": suggestions,
    }
