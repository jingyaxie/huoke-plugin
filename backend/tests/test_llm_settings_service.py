from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.llm_settings_service import (
    bootstrap_llm_settings_from_env_file,
    mask_api_key,
    read_llm_settings,
    resolve_llm_env_file,
    save_llm_settings,
)


def test_mask_api_key() -> None:
    assert mask_api_key("") is None
    assert mask_api_key("sk-abcdefgh") == "sk-***efgh"


def test_resolve_llm_env_file_prefers_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_path = tmp_path / "custom.env.local"
    env_path.write_text("HUOKE_BRIDGE_SECRET=dev\n", encoding="utf-8")
    monkeypatch.setenv("HUOKE_ENV_PATH", str(env_path))
    settings = Settings(storage_root=tmp_path / "storage")
    assert resolve_llm_env_file(settings) == env_path


def test_resolve_llm_env_file_desktop_mode(tmp_path: Path) -> None:
    data_dir = tmp_path / "appdata"
    storage = data_dir / "storage"
    storage.mkdir(parents=True)
    settings = Settings(storage_root=storage, desktop_mode=True)
    assert resolve_llm_env_file(settings) == data_dir / ".env.desktop"


def test_save_and_read_llm_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env.local"
    monkeypatch.setenv("HUOKE_ENV_PATH", str(env_path))
    settings = Settings(
        storage_root=tmp_path,
        database_url=f"sqlite+pysqlite:///{tmp_path}/huoke.db",
    )
    result = save_llm_settings(
        settings,
        {
            "deepseek_api_key": "sk-test-deepseek-key",
            "deepseek_model": "deepseek-chat",
        },
    )
    assert result["ok"] is True
    assert result["llm_configured"] is True
    assert env_path.is_file()
    assert "DEEPSEEK_API_KEY" in env_path.read_text(encoding="utf-8")

    payload = read_llm_settings(settings)
    assert payload["llm_configured"] is True
    assert payload["deepseek"]["configured"] is True
    assert payload["deepseek"]["api_key_masked"] == "sk-***-key"


def test_bootstrap_llm_settings_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "DEEPSEEK_API_KEY=sk-from-local-file\n"
        "DEEPSEEK_MODEL=deepseek-chat\n"
        "AGENT_DEFAULT_PROVIDER=deepseek\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HUOKE_ENV_PATH", str(env_path))
    settings = Settings(
        storage_root=tmp_path,
        database_url=f"sqlite+pysqlite:///{tmp_path}/huoke.db",
        deepseek_api_key=None,
    )
    assert not settings.deepseek_api_key
    bootstrap_llm_settings_from_env_file(settings)
    assert settings.deepseek_api_key == "sk-from-local-file"
    assert settings.deepseek_model == "deepseek-chat"

    payload = read_llm_settings(settings)
    assert payload["llm_configured"] is True
