from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db.bootstrap import ensure_database_schema
from app.db.session import engine


def test_ensure_database_schema_creates_users_table(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "huoke_sidecar.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("DESKTOP_MODE", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    ensure_database_schema()

    inspector = inspect(engine)
    assert "users" in inspector.get_table_names()
