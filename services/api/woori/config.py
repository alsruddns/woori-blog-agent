from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://woori_app@127.0.0.1:5432/woori_blog_agent"
    admin_token: str = Field(min_length=32)


@lru_cache
def settings() -> Settings:
    return Settings()
