from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    llm_key: SecretStr | None = None

    lock_seconds: int = 900
    max_attempts: int = 5
    otp_secret_key: SecretStr
    otp_ttl: int = 300
    is_production: bool = False

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_seconds: int = 900
    refresh_token_expire_days: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
