"""页面失败诊断：跨平台、跨抓取实现，上层契约稳定。"""

from app.services.page_diagnosis.contracts import (
    CrawlFailureSignal,
    FailureClass,
    IssueType,
    PageDiagnosis,
    PageSnapshot,
    Platform,
)
from app.services.page_diagnosis.reporter import CrawlFailureReporter

__all__ = [
    "CrawlFailureSignal",
    "FailureClass",
    "IssueType",
    "PageDiagnosis",
    "PageSnapshot",
    "Platform",
    "CrawlFailureReporter",
]
