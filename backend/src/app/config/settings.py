from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
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
    oauth_state_max_age_seconds: int = 600
    oauth_state_cookie_path: str = "/api/v1/auth"


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


class GoogleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOOGLE_", env_file=ENV_FILE, extra="ignore")

    client_id: str = ""
    client_secret: SecretStr = SecretStr("")

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret.get_secret_value())


class MediaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIA_", env_file=ENV_FILE, extra="ignore")

    # Write access through the S3 Compatibility API; only the local seed uses it.
    s3_endpoint_url: str = ""
    region: str = ""
    bucket: str = ""
    access_key_id: str = ""
    secret_access_key: SecretStr = SecretStr("")
    # Required: every image_url is built from it, so a missing value fails at startup.
    public_base_url: str = Field(min_length=1)

    @field_validator("public_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def can_write(self) -> bool:
        return bool(
            self.s3_endpoint_url
            and self.region
            and self.bucket
            and self.access_key_id
            and self.secret_access_key.get_secret_value()
        )


class BookingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOOKING_", env_file=ENV_FILE, extra="ignore")

    timezone: ZoneInfo = ZoneInfo("Asia/Tbilisi")
    first_slot: time = time(10, 0)
    last_slot: time = time(21, 30)
    slot_minutes: int = 30
    duration_minutes: int = 90
    horizon_days: int = 30
    cancel_cutoff_minutes: int = 30
    # Caps both the party and the table capacity of an instant booking; larger parties send a
    # request that staff confirm.
    max_online_party_size: int = 4
    # The CHECK on bookings.party_size stores at most 8 people.
    max_request_party_size: int = Field(default=8, le=8)
    max_duration_minutes: int = 180
    closing_time: time = time(23, 0)
    preorder_lock_minutes: int = 30
    guest_token_ttl_days: int = 31
    guest_cookie_path: str = "/"


class PreorderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PREORDER_", env_file=ENV_FILE, extra="ignore")

    max_item_quantity: int = 20


class NotificationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOTIFICATIONS_", env_file=ENV_FILE, extra="ignore"
    )

    # Bots and test accounts live there; their in-app notifications are still stored.
    skip_email_domains: list[str] = ["example.com"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    google: GoogleSettings = Field(default_factory=GoogleSettings)
    # mypy sees the required secret_key argument; pydantic-settings fills it from the environment.
    token: TokenSettings = Field(default_factory=TokenSettings)  # type: ignore[arg-type]
    media: MediaSettings = Field(default_factory=MediaSettings)  # type: ignore[arg-type]
    booking: BookingSettings = Field(default_factory=BookingSettings)
    preorder: PreorderSettings = Field(default_factory=PreorderSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)

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
