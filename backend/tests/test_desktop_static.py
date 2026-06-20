from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.desktop_static import mount_desktop_frontend


def test_desktop_spa_serves_index_for_auto_tasks(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")

    app = FastAPI()
    mount_desktop_frontend(app, dist)
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers.get("content-type", "")
    assert "ok" in root.text

    spa = client.get("/auto-tasks")
    assert spa.status_code == 200
    assert "text/html" in spa.headers.get("content-type", "")
    assert "ok" in spa.text


def test_missing_js_asset_returns_404_not_index(tmp_path: Path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = FastAPI()
    mount_desktop_frontend(app, dist)
    client = TestClient(app)

    ok = client.get("/assets/app.js")
    assert ok.status_code == 200

    missing = client.get("/assets/missing-hash.js")
    assert missing.status_code == 404
    assert "text/html" not in missing.headers.get("content-type", "")


def test_validate_desktop_frontend_dist_detects_broken_refs(tmp_path: Path):
    from app.desktop_static import validate_desktop_frontend_dist

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<script type="module" src="/assets/app-abc.js"></script>',
        encoding="utf-8",
    )

    errors = validate_desktop_frontend_dist(dist)
    assert errors == ["broken frontend reference: /assets/app-abc.js"]
