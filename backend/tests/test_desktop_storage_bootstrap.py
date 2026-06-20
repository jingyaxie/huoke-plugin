from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.desktop_storage_bootstrap import CORE_DESKTOP_SKILL_IDS, bootstrap_desktop_storage
from app.services.skill_store import SkillStore


def test_bootstrap_desktop_storage_merges_missing_core_skills(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    bundled = Path(__file__).resolve().parents[1] / "storage" / "skills" / "global.json"
    assert bundled.is_file()

    settings = Settings(
        storage_root=storage,
        desktop_mode=True,
        database_url="sqlite+pysqlite:///:memory:",
    )
    (storage / "skills").mkdir(parents=True)
    (storage / "skills" / "global.json").write_text(
        '{"skills": [{"id":"check-login","name":"x","description":"y","type":"builtin","enabled":true,"scope":"global","parameters":[],"content":"","actions":[],"builtin_handler":"login_status"}]}',
        encoding="utf-8",
    )

    warnings = bootstrap_desktop_storage(settings)
    assert warnings == []

    enabled = {skill.id for skill in SkillStore(settings).list_enabled("default")}
    assert CORE_DESKTOP_SKILL_IDS <= enabled
