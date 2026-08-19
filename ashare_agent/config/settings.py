from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    deepseek_api_key: SecretStr

    deepseek_api_base: str

    deepseek_model: str

    llm_timeout: float = 60.0

    llm_max_retries: int = 2

    cache_redis_url: str = "redis://127.0.0.1:6379/1"

    cache_key_prefix: str = "ashare-agent:cache"

    cache_lock_ttl_seconds: float = Field(default=300, gt=0)

    cache_lock_wait_timeout_seconds: float = Field(default=300, gt=0)

    security_list_cache_ttl_seconds: float = Field(
        default=24 * 60 * 60,
        gt=0,
    )

    company_business_cache_ttl_seconds: float = Field(
        default=7 * 24 * 60 * 60,
        gt=0,
    )

    financial_report_cache_ttl_seconds: float = Field(
        default=24 * 60 * 60,
        gt=0,
    )

    chart_artifact_dir: Path = Path(".artifacts/charts")

    chart_font_family: str = "AR PL UKai CN"

    database_url: str = (
        "postgresql+asyncpg://ashare_agent:ashare_agent@"
        "127.0.0.1:5432/ashare_agent"
    )

    database_auto_create_schema: bool = False

    app_jwt_secret: SecretStr = SecretStr("ashare-agent-local-development-secret")

    app_jwt_expire_hours: int = Field(
        default=12,
        gt=0,
    )

    conversation_context_limit: int = Field(
        default=6,
        ge=0,
        le=50,
    )

    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_job_stream: str = "ashare-agent:jobs"
    redis_job_consumer_group: str = "ashare-agent-workers"
    redis_job_block_ms: int = Field(default=1_000, ge=1, le=60_000)
    redis_job_claim_idle_ms: int = Field(default=5 * 60_000, ge=1)

    job_outbox_dispatch_interval_seconds: float = Field(default=1.0, gt=0)

    demo_username: str = "alice"
    demo_password: SecretStr = SecretStr("alice123")
    demo_display_name: str = "Alice"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
