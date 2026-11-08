from __future__ import annotations

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./smartcane.db"
    jwt_secret: str = DEV_JWT_SECRET  # env JWT_SECRET (MASTER 16.4: real secret only via environment)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    max_batch_records: int = 2000
    scheduler_enabled: bool = True
    escalation_webhook_url: str = ""
    escalation_repeat_minutes: int = 10
    escalation_max_repeats: int = 3  # total notifications per event, including the first


settings = Settings()


def warn_if_weak_secret(log: logging.Logger | None = None) -> bool:
    """Log loudly when the JWT secret is the dev default or too short. Returns True if weak."""
    log = log or logging.getLogger("smartcane")
    s = settings.jwt_secret
    if s == DEV_JWT_SECRET or len(s) < 32:
        log.warning("SECURITY WARNING: JWT_SECRET is %s. Set JWT_SECRET to a random string of at least 32 "
                    "characters before exposing this API.",
                    "the insecure development default" if s == DEV_JWT_SECRET else "shorter than 32 characters")
        return True
    return False
