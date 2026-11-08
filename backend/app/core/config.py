from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./smartcane.db"
    jwt_secret: str = "dev-only-change-me"  # MASTER 16.4: real secret only via environment
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    max_batch_records: int = 2000


settings = Settings()
