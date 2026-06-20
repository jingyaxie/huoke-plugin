from __future__ import annotations

import asyncio


class AgentRunController:
    """Per-run cancellation flags for interrupting agent loops."""

    _instance: AgentRunController | None = None

    def __init__(self) -> None:
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> AgentRunController:
        if cls._instance is None:
            cls._instance = AgentRunController()
        return cls._instance

    async def register(self, run_id: str) -> None:
        async with self._lock:
            self._cancel_events[run_id] = asyncio.Event()

    async def cancel(self, run_id: str) -> bool:
        async with self._lock:
            event = self._cancel_events.get(run_id)
            if event is None:
                return False
            event.set()
            return True

    def is_cancelled(self, run_id: str) -> bool:
        event = self._cancel_events.get(run_id)
        return event.is_set() if event else False

    async def clear(self, run_id: str) -> None:
        async with self._lock:
            self._cancel_events.pop(run_id, None)
