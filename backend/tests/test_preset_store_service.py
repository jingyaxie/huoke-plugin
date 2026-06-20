from __future__ import annotations

from app.core.config import Settings
from app.schemas.presets import PresetCreateRequest, PresetUpdateRequest
from app.services.preset_store_service import PresetStoreService


def test_preset_store_crud(tmp_path):
    settings = Settings(storage_root=tmp_path)
    store = PresetStoreService(settings, "default")

    created = store.create_preset("comments", PresetCreateRequest(name="问候", content="你好 {{nickname}}"))
    assert created.name == "问候"

    listed = store.list_presets("comments")
    assert listed.total == 1
    assert listed.items[0].content.startswith("你好")

    updated = store.update_preset(
        "comments",
        created.id,
        PresetUpdateRequest(name="问候2", content="你好呀 {{nickname}}"),
    )
    assert updated.name == "问候2"

    assert store.delete_preset("comments", created.id) is True
    assert store.list_presets("comments").total == 0
