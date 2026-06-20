from __future__ import annotations

from app.services.page_diagnosis.contracts import FailureClass, IssueType

FAILURE_CLASS_TO_ISSUE: dict[FailureClass, IssueType] = {
    "auth_required": "login_required",
    "auth_expired": "login_expired",
    "captcha": "captcha_required",
    "risk_limit": "risk_control",
    "automation_blocked": "automation_blocked",
    "page_structure": "page_changed",
    "empty_result": "empty_data",
    "network": "network_error",
    "internal": "internal_error",
    "unknown": "unknown",
}

TERMINAL_FAILURE_CLASSES: frozenset[FailureClass] = frozenset(
    {
        "auth_required",
        "auth_expired",
        "captcha",
        "risk_limit",
        "automation_blocked",
    }
)


def issue_type_for(failure_class: FailureClass) -> IssueType:
    return FAILURE_CLASS_TO_ISSUE.get(failure_class, "unknown")
