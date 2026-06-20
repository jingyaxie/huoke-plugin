from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.services.agent_service import AgentService


@dataclass
class EvalCase:
    name: str
    message: str
    expect_status: str = "completed"


class AgentEvalService:
    def __init__(self, settings: Settings, tenant_id: str, platform: str, account_id: str) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.platform = platform
        self.account_id = account_id

    async def run_benchmark(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(cases)
        passed = 0
        details: list[dict[str, Any]] = []
        for item in cases:
            case = EvalCase(
                name=str(item.get("name") or "case"),
                message=str(item.get("message") or ""),
                expect_status=str(item.get("expect_status") or "completed"),
            )
            if not case.message.strip():
                details.append({"name": case.name, "passed": False, "reason": "empty_message"})
                continue
            agent = AgentService(self.settings, self.tenant_id, self.platform, account_id=self.account_id)
            done_data: dict[str, Any] | None = None
            async for event in agent.run_chat(case.message):
                if event.type == "done":
                    done_data = event.data
            got = str((done_data or {}).get("status") or "failed")
            ok = got == case.expect_status
            if ok:
                passed += 1
            details.append(
                {
                    "name": case.name,
                    "expected": case.expect_status,
                    "got": got,
                    "passed": ok,
                    "summary": str((done_data or {}).get("summary") or "")[:200],
                }
            )
        score = round((passed / total) * 100, 1) if total else 0.0
        return {"total": total, "passed": passed, "score": score, "details": details}
