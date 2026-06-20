from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.models import *  # noqa: F401,F403

logger = logging.getLogger(__name__)


def ensure_database_schema() -> None:
    """确保 SQLite / 本地库在首次启动（含桌面 Sidecar）时已建表。"""
    import os

    settings = get_settings()
    if settings.desktop_mode or os.environ.get("DESKTOP_MODE", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        logger.info("desktop mode: skipping alembic, using create_all")
        Base.metadata.create_all(bind=engine)
        return

    backend_dir = Path(__file__).resolve().parents[2]
    ini_path = backend_dir / "alembic.ini"
    if ini_path.is_file():
        try:
            from alembic import command
            from alembic.config import Config

            cfg = Config(str(ini_path))
            cfg.set_main_option("sqlalchemy.url", settings.database_url)
            command.upgrade(cfg, "head")
            return
        except Exception as exc:
            logger.warning("alembic upgrade failed, fallback to create_all: %s", exc)

    Base.metadata.create_all(bind=engine)
