from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://woori_app@127.0.0.1:5432/woori_blog_agent"
    admin_token: str = Field(min_length=32)
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    token_encryption_key: SecretStr = SecretStr("")
    evaluation_database_url: str = ""
    trend_research_hourly_limit: int = Field(default=4, ge=0, le=10)
    google_redirect_uri: Literal["http://127.0.0.1:3100/api/blogger/callback"] = (
        "http://127.0.0.1:3100/api/blogger/callback"
    )


@lru_cache
def settings() -> Settings:
    return Settings()
