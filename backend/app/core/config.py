from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BASE_DIR.parent

# Sidecar / 本地 dev 默认 bridge secret；生产须在 .env 显式配置非默认值
DEFAULT_HUOKE_BRIDGE_SECRET = "dev-bridge-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            BASE_DIR / ".env",
            ROOT_DIR / ".env",
            ROOT_DIR / ".env.local",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Douyin Hot Monitor"
    debug: bool = False
    api_prefix: str = "/api"
    timezone: str = "Asia/Shanghai"

    database_url: str = Field(
        default="sqlite+pysqlite:///./storage/dev/huoke.db"
    )
    sqlite_test_url: str = "sqlite+pysqlite:///:memory:"

    frontend_origin: str = "http://localhost:5173"
    desktop_mode: bool = False
    desktop_port: int = 18765
    frontend_dist_dir: Path = Field(default_factory=lambda: ROOT_DIR / "frontend" / "dist")

    douyin_home_url: str = "https://www.douyin.com"
    douyin_hot_url: str = "https://www.douyin.com/hot"
    default_tenant_id: str = "default"
    default_platform: str = "douyin"
    # 默认使用仓库根目录 storage/
    storage_root: Path = Field(default_factory=lambda: ROOT_DIR / "storage")
    douyin_profile_dir: Path | None = None
    douyin_headless: bool = False

    xhs_home_url: str = "https://www.xiaohongshu.com"
    xhs_explore_url: str = "https://www.xiaohongshu.com/explore"
    xhs_headless: bool = False

    kuaishou_home_url: str = "https://www.kuaishou.com"
    kuaishou_headless: bool = False

    antibot_enabled: bool = True
    antibot_stealth_enabled: bool = True
    antibot_require_login: bool = True
    antibot_delay_min_ms: float = 2000
    antibot_delay_max_ms: float = 6000
    antibot_user_agent: Optional[str] = None
    # mac | linux | auto — 服务器部署建议 mac，避免站点识别为 Linux 数据中心
    antibot_fingerprint_platform: str = "mac"
    antibot_viewport_width: int = 1440
    antibot_viewport_height: int = 1200
    antibot_locale: str = "zh-CN"
    # 仅使用本机 Chrome/Chromium（Playwright channel），不打包内置 Chromium
    antibot_browser_channel: Optional[str] = "chrome"
    antibot_persistent_profile: bool = True
    antibot_warmup_enabled: bool = True

    crawl_cache_ttl_hours: float = 24.0

    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"

    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    agent_max_steps: int = 100
    agent_default_provider: str = "deepseek"
    agent_headless: bool = False
    agent_vision_enabled: bool = True
    agent_vision_model: Optional[str] = None
    agent_max_history_messages: int = 40
    agent_default_run_mode: str = "auto"
    agent_checkpoints_enabled: bool = True
    agent_checkpoint_max_count: int = 20
    agent_subagent_max_steps: int = 100
    agent_stream_enabled: bool = True
    agent_browser_start_timeout_seconds: int = 90
    agent_compress_enabled: bool = True
    agent_compress_threshold_messages: int = 30
    agent_compress_keep_recent: int = 12
    agent_dream_enabled: bool = True
    agent_dream_auto: bool = True
    agent_dream_use_llm: bool = False
    agent_dream_inject_max: int = 5

    skillhub_registry: str = "https://skill.xfyun.cn"
    skillhub_token: Optional[str] = None
    skillhub_auto_install_enabled: bool = True
    skillhub_script_timeout_seconds: int = 120

    report_output_dir: Path = BASE_DIR / "reports"

    tenant_auth_enabled: bool = False
    tenant_auth_pepper: str = "change-me-in-production"
    user_auth_pepper: str = "change-me-in-production"
    jwt_secret: str = "change-me-jwt-secret-in-production"
    jwt_expire_minutes: int = 60 * 24 * 7
    huoke_bridge_secret: str = Field(default=DEFAULT_HUOKE_BRIDGE_SECRET)

    @field_validator("huoke_bridge_secret", mode="before")
    @classmethod
    def _coerce_huoke_bridge_secret(cls, value: object) -> str:
        if value is None:
            return DEFAULT_HUOKE_BRIDGE_SECRET
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or DEFAULT_HUOKE_BRIDGE_SECRET
        text = str(value).strip()
        return text or DEFAULT_HUOKE_BRIDGE_SECRET

    admin_api_secret: Optional[str] = None
    tenant_bootstrap_api_keys: Optional[str] = None
    storage_state_encryption_key: Optional[str] = None
    task_job_concurrency: int = 2
    task_scheduler_poll_seconds: int = 30

    # 抓取失败页面诊断（由 storage/settings/page_diagnosis.json + 设置页维护，非环境变量）
    page_diagnosis_enabled: bool = True
    page_diagnosis_llm_enabled: bool = True
    page_diagnosis_screenshot_enabled: bool = True
    page_diagnosis_llm_timeout_seconds: int = 8
    page_diagnosis_rule_confidence_skip_llm: float = 0.92
    page_diagnosis_screenshot_max_bytes: int = 800_000
    page_diagnosis_body_excerpt_chars: int = 2000

    # V3 TikHub compat layer (AISales acquisition router)
    compat_enabled: bool = True
    compat_max_concurrent: int = 3
    compat_default_timeout_seconds: int = 25

    # 抖音 On-Device Hook Bridge（LSPosed，非 MITM）；Mac 开发经 adb forward 访问 127.0.0.1:59528
    douyin_mobile_hook_enabled: bool = True
    douyin_mobile_hook_host: str = "127.0.0.1"
    douyin_mobile_hook_port: int = 59528
    douyin_mobile_hook_timeout_seconds: float = 8.0
    douyin_mobile_hook_token: Optional[str] = None
    douyin_mobile_hook_adb_serial: Optional[str] = None
    douyin_mobile_hook_auto_forward: bool = True


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    root = settings.storage_root
    settings.storage_root = root.resolve() if root.is_absolute() else (ROOT_DIR / root).resolve()
    if settings.douyin_profile_dir is None:
        settings.douyin_profile_dir = settings.storage_root / "douyin" / "profile"
    else:
        profile = settings.douyin_profile_dir
        settings.douyin_profile_dir = (
            profile.resolve() if profile.is_absolute() else (ROOT_DIR / profile).resolve()
        )
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.douyin_profile_dir.mkdir(parents=True, exist_ok=True)
    settings.report_output_dir.mkdir(parents=True, exist_ok=True)
    dist = settings.frontend_dist_dir
    settings.frontend_dist_dir = dist.resolve() if dist.is_absolute() else (ROOT_DIR / dist).resolve()
    from app.services.llm_settings_service import bootstrap_llm_settings_from_env_file
    from app.services.page_diagnosis_settings_service import bootstrap_page_diagnosis_settings

    bootstrap_llm_settings_from_env_file(settings)
    bootstrap_page_diagnosis_settings(settings)
    return settings
