from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from sqlalchemy import URL

# backend/.env, read when it exists (local runs only: containers get real environment variables).
# extra="ignore" everywhere, because the shared .env holds every prefix's keys.
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

Environment = Literal["local", "dev", "staging", "prod"]


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=ENV_FILE, extra="ignore")

    name: str = "backend-showcase"
    environment: Environment = "local"
    frontend_url: str = "https://family-rest.vercel.app"
    backend_url: str = "https://backend-showcase-dev.duckdns.org"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_", env_file=ENV_FILE, extra="ignore")

    host: str = "127.0.0.1"
    port: int = 5433
    user: str = "app"
    password: SecretStr = SecretStr("app")
    name: str = "app"
    # Must stay under the 2 s urlopen timeout of the Dockerfile HEALTHCHECK.
    probe_timeout_seconds: float = 1.0

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


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=ENV_FILE, extra="ignore")

    verification_code_ttl_minutes: int = 10
    resend_cooldown_seconds: int = 60
    max_code_attempts: int = 5
    max_codes_per_hour: int = 5
    max_reset_codes_per_day: int = 10
    max_login_attempts: int = 5
    login_lockout_minutes: int = 5


class TokenSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOKEN_", env_file=ENV_FILE, extra="ignore")

    # Required: a missing or short key fails at startup instead of signing tokens weakly.
    secret_key: SecretStr = Field(min_length=32)
    # HMAC only: an asymmetric algorithm needs a key pair, not a shared secret.
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 30
    access_cookie_path: str = "/"
    refresh_cookie_path: str = "/api/v1/auth"


class EmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMAIL_", env_file=ENV_FILE, extra="ignore")

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: str = ""
    password: SecretStr = SecretStr("")
    sender: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.password.get_secret_value() and self.sender)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    # mypy sees the required secret_key argument; pydantic-settings fills it from the environment.
    token: TokenSettings = Field(default_factory=TokenSettings)  # type: ignore[arg-type]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Each block reads its own prefixed variables. The root reads none, so an unrelated
        # shell variable such as EMAIL is never parsed as a whole block.
        return (init_settings,)


@lru_cache
def get_settings() -> Settings:
    return Settings()
