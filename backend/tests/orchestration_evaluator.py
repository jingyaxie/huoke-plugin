"""编排与执行流程自动评估器（用于大规模模拟测试）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.task_brief_service import TaskBrief
from app.services.task_round_service import goal_reached_for_current_round
from tests.task_execution_simulator import SimulationResult, SimulationStep
from tests.test_task_form_orchestration_audit import (
    CRAWL_ACTIONS,
    OUTREACH_ACTIONS,
    audit_execution_plan,
)


@dataclass
class EvaluationIssue:
    code: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ExecutionQualityReport:
    passed: bool
    issues: list[EvaluationIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def add(self, code: str, message: str, *, severity: str = "error") -> None:
        self.issues.append(EvaluationIssue(code=code, message=message, severity=severity))
        if severity == "error":
            self.passed = False


def _classify_action(action: str) -> str:
    if action in CRAWL_ACTIONS:
        return "crawl"
    if action == "evaluate_leads":
        return "evaluate"
    if action == "query_stats":
        return "stats"
    if action in OUTREACH_ACTIONS:
        return "outreach"
    if action == "complete":
        return "complete"
    if action == "suspend":
        return "suspend"
    return "other"


def evaluate_execution_trace(
    result: SimulationResult,
    *,
    brief: TaskBrief,
    expected_first_crawl: str,
    max_reasonable_cycles: int = 80,
    allow_suspend: bool = True,
    require_goal_or_suspend: bool = True,
) -> ExecutionQualityReport:
    """评估模拟执行轨迹的合理性与容错表现。"""
    report = ExecutionQualityReport(passed=True)
    actions = result.actions
    trace = result.trace
    state = result.state

    report.metrics = {
        "cycle_count": len(trace),
        "terminal": result.terminal,
        "completion_outcome": result.completion_outcome,
        "failure_events": len(result.failure_events),
        "recovered_actions": list(result.recovered_actions),
        "crawl_done": bool(state.get("crawl_done")),
        "evaluation_done": bool(state.get("evaluation_done")),
        "leads_collected": int(state.get("leads_collected") or 0),
    }

    if not trace:
        report.add("empty_trace", "执行轨迹为空")
        return report

    if len(trace) > max_reasonable_cycles:
        report.add(
            "excessive_cycles",
            f"循环次数 {len(trace)} 超过上限 {max_reasonable_cycles}，可能存在死循环",
        )

    if actions[0] != expected_first_crawl:
        report.add(
            "wrong_first_action",
            f"首步应为 {expected_first_crawl}，实际 {actions[0]}",
        )

    # 流水线阶段顺序（允许触达步交错重复）
    phases = [_classify_action(a) for a in actions]
    first_indices: dict[str, int] = {}
    for i, phase in enumerate(phases):
        if phase not in first_indices:
            first_indices[phase] = i

    for earlier, later in [
        ("crawl", "evaluate"),
        ("evaluate", "stats"),
        ("stats", "outreach"),
    ]:
        if earlier in first_indices and later in first_indices:
            if first_indices[earlier] > first_indices[later]:
                report.add(
                    "pipeline_order",
                    f"阶段顺序错误: {earlier} 首次出现晚于 {later}",
                )

    crawl_count = sum(1 for a in actions if a in CRAWL_ACTIONS)
    if crawl_count > 5:
        report.add(
            "crawl_loop",
            f"抓取动作重复 {crawl_count} 次，超过合理上限",
            severity="warning",
        )

    repeat_runs = _max_consecutive(actions)
    if repeat_runs > 4:
        report.add(
            "action_stutter",
            f"同一动作连续重复 {repeat_runs} 次，可能卡死",
        )

    terminal = result.terminal or ""
    if terminal == "max_cycles":
        report.add("max_cycles_hit", "达到 max_cycles 上限仍未正常结束")

    if terminal == "no_decision":
        report.add("no_decision", "决策器返回空，流程异常中断")

    if require_goal_or_suspend:
        if terminal == "complete":
            if result.completion_outcome == "goal_reached":
                if not goal_reached_for_current_round(brief, state):
                    target = brief.goals.get("target_leads") or brief.goals.get("round_target_count")
                    report.add(
                        "false_complete",
                        f"标记 goal_reached 但未达目标 (target={target}, collected={state.get('leads_collected')})",
                    )
            elif result.completion_outcome not in {
                "goal_reached",
                "max_rounds_reached",
                None,
                "",
            }:
                report.add(
                    "unexpected_complete_outcome",
                    f"complete 但 outcome={result.completion_outcome}",
                    severity="warning",
                )
        elif terminal == "suspend":
            if not allow_suspend:
                report.add("unexpected_suspend", "不应挂起但进入了 suspend")
            elif not state.get("suspended") and not result.completion_outcome:
                report.add(
                    "suspend_without_state",
                    "terminal=suspend 但 state.suspended 未设置",
                    severity="warning",
                )
        elif terminal in {"partial", "single_step"}:
            pass
        elif terminal not in {"complete", "suspend", "partial", "single_step"}:
            report.add("bad_terminal", f"异常终止状态: {terminal}")

    plan = state.get("execution_plan") or {}
    steps = plan.get("steps") or []
    if isinstance(steps, list) and steps:
        failed_required = [
            s.get("action")
            for s in steps
            if isinstance(s, dict) and s.get("required") and s.get("status") == "failed"
        ]
        if failed_required and terminal == "complete" and result.completion_outcome == "goal_reached":
            report.add(
                "failed_required_on_complete",
                f"required 步骤失败却标记完成: {failed_required}",
            )

    if result.failure_events and terminal == "complete" and result.completion_outcome == "goal_reached":
        if not result.recovered_actions and not result.progressed_after_failure:
            report.add(
                "failure_without_recovery",
                "存在失败事件但流程未继续推进",
                severity="warning",
            )

    return report


def evaluate_orchestration_plan(
    plan: dict[str, Any],
    *,
    expected_first_crawl: str,
) -> ExecutionQualityReport:
    """评估战术执行计划结构。"""
    report = ExecutionQualityReport(passed=True)
    raw_issues = audit_execution_plan(plan, expected_first_crawl=expected_first_crawl)
    for msg in raw_issues:
        report.add("plan_audit", msg)
    report.metrics["step_count"] = len(plan.get("steps") or [])
    return report


def evaluate_submission_to_execution(
    *,
    plan_report: ExecutionQualityReport,
    exec_report: ExecutionQualityReport,
    preflight_actions: list[str] | None = None,
    created_actions: list[str] | None = None,
) -> ExecutionQualityReport:
    """合并提交→编排→执行各阶段评估。"""
    merged = ExecutionQualityReport(passed=plan_report.passed and exec_report.passed)
    merged.issues.extend(plan_report.issues)
    merged.issues.extend(exec_report.issues)
    merged.metrics = {
        "plan": plan_report.metrics,
        "execution": exec_report.metrics,
    }

    if preflight_actions and created_actions and preflight_actions != created_actions:
        merged.add(
            "preflight_create_mismatch",
            f"预检与创建编排不一致: preflight={preflight_actions} created={created_actions}",
        )

    return merged


def _max_consecutive(actions: list[str]) -> int:
    if not actions:
        return 0
    best = 1
    cur = 1
    for i in range(1, len(actions)):
        if actions[i] == actions[i - 1]:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def format_report(report: ExecutionQualityReport) -> str:
    lines = [f"passed={report.passed}"]
    for issue in report.issues:
        lines.append(f"  [{issue.severity}] {issue.code}: {issue.message}")
    if report.metrics:
        lines.append(f"  metrics={report.metrics}")
    return "\n".join(lines)
