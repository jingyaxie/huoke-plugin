from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from desktop_bundle_runtime import (  # noqa: E402
    collect_bundle_integrity_issues,
    runtime_workdir_backend_ready,
)


def test_collect_bundle_integrity_issues_flags_missing_core_files(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "runtime" / "python").mkdir(parents=True)
    (bundle / "runtime" / "python" / "python.exe").write_bytes(b"py")
    issues = collect_bundle_integrity_issues(bundle)
    assert any("backend/app/main.py" in item for item in issues)
    assert any("frontend-dist/index.html" in item for item in issues)
    assert not runtime_workdir_backend_ready(bundle)


def test_runtime_workdir_ready_when_core_files_present(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "runtime" / "python").mkdir(parents=True)
    (bundle / "runtime" / "python" / "python.exe").write_bytes(b"py")
    (bundle / "backend" / "app").mkdir(parents=True)
    (bundle / "backend" / "app" / "main.py").write_text("app = 1\n", encoding="utf-8")
    (bundle / "backend" / "storage" / "skills").mkdir(parents=True)
    (bundle / "backend" / "storage" / "skills" / "global.json").write_text(
        '{"skills": []}',
        encoding="utf-8",
    )
    (bundle / "frontend-dist").mkdir()
    (bundle / "frontend-dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    for idx in range(12):
        (bundle / "backend" / f"module_{idx}.py").write_text("x = 1\n", encoding="utf-8")

    assert collect_bundle_integrity_issues(bundle) == []
    assert runtime_workdir_backend_ready(bundle)


def test_repo_backend_storage_has_bundled_skills() -> None:
    skills_path = Path(__file__).resolve().parents[1] / "storage" / "skills" / "global.json"
    assert skills_path.is_file()
    text = skills_path.read_text(encoding="utf-8")
    for skill_id in (
        "douyin-keyword-comments",
        "reply-comment",
        "send-dm",
        "follow-user",
    ):
        assert skill_id in text
