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

    cache_db_path: Path = Path(".cache/ashare-agent.sqlite3")

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

    app_db_path: Path = Path(".data/ashare-agent.sqlite3")

    app_jwt_secret: SecretStr = SecretStr("ashare-agent-local-development-secret")

    app_jwt_expire_hours: int = Field(
        default=12,
        gt=0,
    )

    app_job_max_concurrency: int = Field(
        default=4,
        ge=1,
    )

    conversation_context_limit: int = Field(
        default=6,
        ge=0,
        le=50,
    )

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
