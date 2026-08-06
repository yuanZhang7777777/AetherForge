"""AetherForge 后端配置：从环境变量读取，不落盘密钥值。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # DeepSeek
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"))
    deepseek_prompt_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_PROMPT_MODEL", "deepseek-v4-flash"))
    deepseek_design_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_DESIGN_MODEL", "") or os.getenv("DEEPSEEK_PROMPT_MODEL", "deepseek-v4-flash"))

    # APIMart
    apimart_api_key: str = field(default_factory=lambda: os.getenv("APIMART_API_KEY", ""))
    apimart_base_url: str = field(default_factory=lambda: os.getenv("APIMART_BASE_URL", "https://api.apimart.ai/v1").rstrip("/"))
    apimart_vision_model: str = field(default_factory=lambda: os.getenv("APIMART_VISION_MODEL", "gpt-5-nano-2025-08-07"))
    apimart_image_model: str = field(default_factory=lambda: os.getenv("APIMART_IMAGE_MODEL", "gpt-image-2"))

    # OSS
    storage_backend: str = field(default_factory=lambda: os.getenv("STORAGE_BACKEND", "local"))
    oss_endpoint: str = field(default_factory=lambda: os.getenv("OSS_ENDPOINT", ""))
    oss_bucket: str = field(default_factory=lambda: os.getenv("OSS_BUCKET", ""))
    oss_access_key_id: str = field(default_factory=lambda: os.getenv("OSS_ACCESS_KEY_ID", ""))
    oss_access_key_secret: str = field(default_factory=lambda: os.getenv("OSS_ACCESS_KEY_SECRET", ""))
    oss_prefix: str = field(default_factory=lambda: os.getenv("OSS_PREFIX", "aetherforge"))

    # ERP 登录（照搬 picturesGenerate）
    erp_login_url: str = field(default_factory=lambda: os.getenv("ERP_LOGIN_URL", ""))
    platform_admin_erp_users: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            u.strip() for u in os.getenv("PLATFORM_ADMIN_ERP_USERS", "").split(",") if u.strip()
        )
    )
    catalog_timeout_seconds: int = field(default_factory=lambda: _int(os.getenv("CATALOG_TIMEOUT_SECONDS"), 15))

    # runtime
    offline_mode: bool = field(default_factory=lambda: _bool(os.getenv("OFFLINE_MODE"), False))
    prompt_timeout_seconds: int = field(default_factory=lambda: _int(os.getenv("PROMPT_TIMEOUT_SECONDS"), 180))
    reasoning_effort_deep: str = field(default_factory=lambda: os.getenv("REASONING_EFFORT_DEEP", "high"))
    reasoning_effort_compile: str = field(default_factory=lambda: os.getenv("REASONING_EFFORT_COMPILE", "low"))
    deepseek_temperature: float = field(default_factory=lambda: _float(os.getenv("DEEPSEEK_TEMPERATURE"), 1.3))
    max_tokens_deep: int = field(default_factory=lambda: _int(os.getenv("MAX_TOKENS_DEEP"), 16384))
    # 写提示词单次调用：think 高会把额度全烧在推理上，须留足输出空间给 9 张完整英文提示词
    max_tokens_prompts: int = field(default_factory=lambda: _int(os.getenv("MAX_TOKENS_PROMPTS"), 32768))
    max_tokens_compile: int = field(default_factory=lambda: _int(os.getenv("MAX_TOKENS_COMPILE"), 8192))

    # database / auth
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./aetherforge.db"))
    db_pool_size: int = field(default_factory=lambda: _int(os.getenv("DB_POOL_SIZE"), 15))
    db_max_overflow: int = field(default_factory=lambda: _int(os.getenv("DB_MAX_OVERFLOW"), 30))
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", "dev-insecure-session-secret"))
    session_max_age_seconds: int = field(default_factory=lambda: _int(os.getenv("SESSION_MAX_AGE_SECONDS"), 60 * 60 * 24 * 7))

    # seed admin
    seed_admin_username: str = field(default_factory=lambda: os.getenv("SEED_ADMIN_USERNAME", "admin"))
    seed_admin_password: str = field(default_factory=lambda: os.getenv("SEED_ADMIN_PASSWORD", "admin123"))
    seed_admin_email: str = field(default_factory=lambda: os.getenv("SEED_ADMIN_EMAIL", "admin@aetherforge.local"))

    # quota / worker
    user_daily_generation_limit: int = field(default_factory=lambda: _int(os.getenv("USER_DAILY_GENERATION_LIMIT"), 100))
    max_active_generations: int = field(default_factory=lambda: _int(os.getenv("MAX_ACTIVE_GENERATIONS"), 100))
    max_concurrent_prepares: int = field(default_factory=lambda: _int(os.getenv("MAX_CONCURRENT_PREPARES"), 100))
    generation_poll_interval_seconds: int = field(default_factory=lambda: _int(os.getenv("GENERATION_POLL_INTERVAL_SECONDS"), 6))
    generation_max_polls: int = field(default_factory=lambda: _int(os.getenv("GENERATION_MAX_POLLS"), 300))

    # media / deploy
    media_root: str = field(default_factory=lambda: os.getenv("AETHERFORGE_MEDIA_ROOT", "./media").rstrip("/"))

    @property
    def has_credentials(self) -> bool:
        return bool(self.deepseek_api_key and self.apimart_api_key)


settings = Settings()
