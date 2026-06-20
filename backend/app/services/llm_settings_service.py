from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.core.config import ROOT_DIR, Settings, get_settings
from app.services.ai_client import AIClientFactory

_LLM_ENV_KEYS = frozenset(
    {
        "AGENT_DEFAULT_PROVIDER",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
    }
)

_SETTINGS_FIELD_MAP: dict[str, str] = {
    "AGENT_DEFAULT_PROVIDER": "agent_default_provider",
    "DEEPSEEK_API_KEY": "deepseek_api_key",
    "DEEPSEEK_BASE_URL": "deepseek_base_url",
    "DEEPSEEK_MODEL": "deepseek_model",
}


def mask_api_key(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:3]}***{raw[-4:]}"


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        raw = value.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
            raw = raw[1:-1]
        if key:
            out[key] = raw
    return out


def bootstrap_llm_settings_from_env_file(settings: Settings) -> None:
    """进程重启后从本机 .env.local / .env.desktop 恢复 LLM 配置。"""
    env_path = resolve_llm_env_file(settings)
    parsed = _parse_env_file(env_path)
    if not parsed:
        return
    updates: dict[str, str | None] = {}
    for env_key, field in _SETTINGS_FIELD_MAP.items():
        current = getattr(settings, field, None)
        if current is not None and str(current).strip():
            continue
        raw = parsed.get(env_key)
        if raw is not None and str(raw).strip():
            updates[env_key] = str(raw).strip()
    if updates:
        apply_llm_settings_to_runtime(settings, updates)


def resolve_llm_env_file(settings: Settings) -> Path:
    explicit = str(
        os.environ.get("HUOKE_ENV_PATH")
        or os.environ.get("HUOKE_ENV_SIDECAR_PATH")
        or ""
    ).strip()
    if explicit:
        return Path(explicit).expanduser()
    if settings.desktop_mode:
        return settings.storage_root.parent / ".env.desktop"
    return ROOT_DIR / ".env.local"


def _quote_env_value(value: str) -> str:
    if not value:
        return '""'
    if re.search(r'[\s#"\']', value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _write_env_updates(path: Path, updates: dict[str, str | None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    seen: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    seen.add(key)
                    value = updates[key]
                    if value is not None and str(value).strip():
                        lines.append(f"{key}={_quote_env_value(str(value).strip())}")
                    continue
            lines.append(line)
    for key, value in updates.items():
        if key in seen:
            continue
        if value is None or not str(value).strip():
            continue
        lines.append(f"{key}={_quote_env_value(str(value).strip())}")
    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def _provider_out(*, configured: bool, api_key: str | None, base_url: str, model: str):
    from app.schemas.llm_settings import LlmProviderSettingsOut

    return LlmProviderSettingsOut(
        configured=configured,
        api_key_masked=mask_api_key(api_key) if configured else None,
        base_url=base_url,
        model=model,
    )


def read_llm_settings(settings: Settings) -> dict[str, Any]:
    from app.schemas.llm_settings import LlmSettingsOut

    bootstrap_llm_settings_from_env_file(settings)
    factory = AIClientFactory(settings)
    payload = LlmSettingsOut(
        env_file=str(resolve_llm_env_file(settings)),
        deepseek=_provider_out(
            configured=bool(settings.deepseek_api_key),
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        ),
        llm_configured=factory.llm_configured(),
    )
    return payload.model_dump()


def _build_env_updates(payload: dict[str, Any]) -> dict[str, str | None]:
    updates: dict[str, str | None] = {}
    if "deepseek_base_url" in payload and payload["deepseek_base_url"] is not None:
        updates["DEEPSEEK_BASE_URL"] = str(payload["deepseek_base_url"]).strip() or None
    if "deepseek_model" in payload and payload["deepseek_model"] is not None:
        updates["DEEPSEEK_MODEL"] = str(payload["deepseek_model"]).strip() or None
    if "deepseek_api_key" in payload:
        raw = payload["deepseek_api_key"]
        if raw is None:
            pass
        elif not str(raw).strip():
            updates["DEEPSEEK_API_KEY"] = None
        else:
            updates["DEEPSEEK_API_KEY"] = str(raw).strip()
    if updates:
        updates["AGENT_DEFAULT_PROVIDER"] = "deepseek"
    return {key: value for key, value in updates.items() if key in _LLM_ENV_KEYS}


def apply_llm_settings_to_runtime(settings: Settings, updates: dict[str, str | None]) -> None:
    for env_key, value in updates.items():
        field = _SETTINGS_FIELD_MAP.get(env_key)
        if not field:
            continue
        setattr(settings, field, None if value is None else str(value).strip() or None)


def save_llm_settings(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    from app.schemas.llm_settings import LlmSettingsUpdateResult

    updates = _build_env_updates(payload)
    if not updates:
        current = read_llm_settings(settings)
        return LlmSettingsUpdateResult(
            ok=True,
            llm_configured=bool(current.get("llm_configured")),
            message="无变更",
        ).model_dump()

    env_path = resolve_llm_env_file(settings)
    _write_env_updates(env_path, updates)
    apply_llm_settings_to_runtime(settings, updates)

    refreshed = read_llm_settings(settings)
    return LlmSettingsUpdateResult(
        ok=True,
        llm_configured=bool(refreshed.get("llm_configured")),
        message="已保存到本机配置并立即生效",
    ).model_dump()


def patch_cached_settings(settings: Settings) -> None:
    cached = get_settings()
    if cached is settings:
        return
    for field in _SETTINGS_FIELD_MAP.values():
        setattr(cached, field, getattr(settings, field))
