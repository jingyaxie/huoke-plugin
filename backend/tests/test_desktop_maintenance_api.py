from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.desktop_maintenance_service import (
    collect_bundle_integrity_issues,
    repair_desktop_runtime,
    resolve_desktop_data_dir,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_collect_bundle_integrity_issues_flags_missing_files(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    issues = collect_bundle_integrity_issues(bundle)
    assert any("backend/app/main.py" in item for item in issues)


def test_repair_desktop_runtime_clears_cache_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "runtime-work" / "current").mkdir(parents=True)
    (data_dir / "bundle-cache" / "current").mkdir(parents=True)
    (data_dir / "storage").mkdir()
    monkeypatch.setenv("HUOKE_DATA_DIR", str(data_dir))

    settings = get_settings()
    result = repair_desktop_runtime(settings)
    assert result["need_restart"] is True
    assert not (data_dir / "runtime-work").exists()
    assert not (data_dir / "bundle-cache").exists()
    assert (data_dir / "storage").exists()


def test_desktop_repair_api_requires_desktop_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setenv("STORAGE_ROOT", str(storage))
    monkeypatch.delenv("DESKTOP_MODE", raising=False)
    get_settings.cache_clear()

    client = TestClient(app)
    response = client.post("/api/desktop/repair")
    assert response.status_code == 404


def test_desktop_repair_and_diagnostics_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    storage = data_dir / "storage"
    storage.mkdir(parents=True)
    skills_dir = storage / "skills"
    skills_dir.mkdir()
    (skills_dir / "global.json").write_text(
        '{"skills": [{"id": "check-login", "enabled": true}]}',
        encoding="utf-8",
    )
    (data_dir / "runtime-work").mkdir()
    monkeypatch.setenv("HUOKE_DATA_DIR", str(data_dir))
    monkeypatch.setenv("STORAGE_ROOT", str(storage))
    monkeypatch.setenv("DESKTOP_MODE", "true")
    get_settings.cache_clear()

    client = TestClient(app)
    repair = client.post("/api/desktop/repair")
    assert repair.status_code == 200
    payload = repair.json()
    assert payload["need_restart"] is True
    assert payload["cleared"]

    export = client.get("/api/desktop/diagnostics")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        names = archive.namelist()
        assert "diagnostics.json" in names
        diagnostics = json.loads(archive.read("diagnostics.json").decode("utf-8"))
        assert diagnostics["desktop_mode"] is True
        assert diagnostics["skills"]["skill_count"] == 1


def test_resolve_desktop_data_dir_prefers_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    monkeypatch.setenv("HUOKE_DATA_DIR", str(data_dir))
    settings = get_settings()
    assert resolve_desktop_data_dir(settings) == data_dir.resolve()
