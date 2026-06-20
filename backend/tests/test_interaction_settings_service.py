from __future__ import annotations

import tempfile
from pathlib import Path

from app.core.config import Settings
from app.schemas.interaction_settings import InteractionSettingsUpdate
from app.services.interaction_settings_service import InteractionSettingsService


def test_interaction_settings_defaults_and_patch():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(storage_root=Path(tmp))
        svc = InteractionSettingsService(settings, "default")
        initial = svc.read()
        assert initial.comment_dm_percentage == 50
        assert initial.follow_per_day == 30

        saved = svc.save(
            InteractionSettingsUpdate(
                comment_dm_percentage=80,
                dm_per_day=15,
            )
        )
        assert saved.comment_dm_percentage == 80
        assert saved.dm_per_day == 15
        assert saved.comment_dm_interval_seconds_min == 10

        reloaded = svc.read()
        assert reloaded.comment_dm_percentage == 80
        assert reloaded.dm_per_day == 15
