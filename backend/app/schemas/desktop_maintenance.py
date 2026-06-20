from __future__ import annotations

from pydantic import BaseModel, Field


class DesktopRepairResult(BaseModel):
    message: str
    cleared: list[str] = Field(default_factory=list)
    data_dir: str = ""
    need_restart: bool = True
