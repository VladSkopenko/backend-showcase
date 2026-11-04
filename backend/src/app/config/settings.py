from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    name: str = "backend-showcase"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    host: str = "127.0.0.1"
    port: int = 5433
    user: str = "app"
    password: SecretStr = SecretStr("app")
    name: str = "app"

    @property
    def url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )


class Settings(BaseSettings):
    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()
