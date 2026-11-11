from datetime import time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.config.settings import DatabaseSettings, MediaSettings, Settings, TokenSettings


def test_env_vars_land_in_their_domain_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "custom-name")
    monkeypatch.setenv("DATABASE_HOST", "db.internal")
    monkeypatch.setenv("DATABASE_PORT", "6543")
    monkeypatch.setenv("DATABASE_USER", "svc")
    monkeypatch.setenv("DATABASE_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_NAME", "showcase")
    monkeypatch.setenv("APP_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_FRONTEND_URL", "https://front.example")
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "2525")
    monkeypatch.setenv("EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    monkeypatch.setenv("EMAIL_SENDER", "sender@example.com")
    monkeypatch.setenv("AUTH_VERIFICATION_CODE_TTL_MINUTES", "15")
    monkeypatch.setenv("AUTH_RESEND_COOLDOWN_SECONDS", "30")
    monkeypatch.setenv("AUTH_MAX_CODE_ATTEMPTS", "3")
    monkeypatch.setenv("AUTH_MAX_CODES_PER_HOUR", "7")
    monkeypatch.setenv("AUTH_MAX_RESET_CODES_PER_DAY", "20")

    settings = Settings()

    assert settings.app.name == "custom-name"
    assert settings.app.environment == "staging"
    assert settings.app.frontend_url == "https://front.example"
    assert settings.email.smtp_host == "smtp.example.com"
    assert settings.email.smtp_port == 2525
    assert settings.email.username == "sender@example.com"
    assert settings.email.password.get_secret_value() == "app-password"
    assert settings.email.sender == "sender@example.com"
    assert settings.auth.verification_code_ttl_minutes == 15
    assert settings.auth.resend_cooldown_seconds == 30
    assert settings.auth.max_code_attempts == 3
    assert settings.auth.max_codes_per_hour == 7
    assert settings.auth.max_reset_codes_per_day == 20
    assert settings.database.host == "db.internal"
    assert settings.database.port == 6543
    assert settings.database.user == "svc"
    assert settings.database.password.get_secret_value() == "s3cret"
    assert settings.database.name == "showcase"


def test_database_probe_timeout_env_var_lands_in_the_database_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PROBE_TIMEOUT_SECONDS", "0.5")

    settings = Settings()

    assert settings.database.probe_timeout_seconds == 0.5


def test_database_probe_timeout_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_PROBE_TIMEOUT_SECONDS", raising=False)

    settings = Settings()

    assert settings.database.probe_timeout_seconds == 1.0


def test_database_url_escapes_special_characters_in_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_HOST", "db.internal")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_USER", "app")
    monkeypatch.setenv("DATABASE_PASSWORD", "p@ss/word")
    monkeypatch.setenv("DATABASE_NAME", "app")

    url = DatabaseSettings().url

    assert url.password == "p@ss/word"
    assert (
        url.render_as_string(hide_password=False)
        == "postgresql+asyncpg://app:p%40ss%2Fword@db.internal:5432/app"
    )


def test_password_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PASSWORD", "p@ss/word")

    settings = Settings()

    assert "p@ss/word" not in repr(settings)
    assert "p@ss/word" not in repr(settings.database.url)


def test_settings_build_with_a_stray_email_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL", "x")

    settings = Settings()

    assert settings.email.username == ""


def test_token_env_vars_land_in_the_token_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SECRET_KEY", "f" * 64)
    monkeypatch.setenv("TOKEN_ALGORITHM", "HS512")
    monkeypatch.setenv("TOKEN_ACCESS_TTL_MINUTES", "5")
    monkeypatch.setenv("TOKEN_ACCESS_COOKIE_PATH", "/app")
    monkeypatch.setenv("TOKEN_REFRESH_TTL_DAYS", "7")
    monkeypatch.setenv("TOKEN_REFRESH_COOKIE_PATH", "/api/v2/auth")
    monkeypatch.setenv("AUTH_MAX_LOGIN_ATTEMPTS", "3")
    monkeypatch.setenv("AUTH_LOGIN_LOCKOUT_MINUTES", "10")

    settings = Settings()

    assert settings.token.secret_key.get_secret_value() == "f" * 64
    assert settings.token.algorithm == "HS512"
    assert settings.token.access_ttl_minutes == 5
    assert settings.token.access_cookie_path == "/app"
    assert settings.token.refresh_ttl_days == 7
    assert settings.token.refresh_cookie_path == "/api/v2/auth"
    assert settings.auth.max_login_attempts == 3
    assert settings.auth.login_lockout_minutes == 10


def test_token_defaults() -> None:
    settings = Settings()

    assert settings.token.algorithm == "HS256"
    assert settings.token.access_ttl_minutes == 15
    assert settings.token.access_cookie_path == "/"
    assert settings.token.refresh_ttl_days == 30
    assert settings.token.refresh_cookie_path == "/api/v1/auth"
    assert settings.auth.max_login_attempts == 5
    assert settings.auth.login_lockout_minutes == 5


def test_token_secret_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SECRET_KEY", "s" * 40)

    settings = Settings()

    assert "s" * 40 not in repr(settings)


def test_missing_token_secret_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TOKEN_SECRET_KEY")

    with pytest.raises(ValidationError, match="secret_key"):
        TokenSettings()  # type: ignore[call-arg]


def test_short_token_secret_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SECRET_KEY", "a" * 31)

    with pytest.raises(ValidationError, match="secret_key"):
        TokenSettings()  # type: ignore[call-arg]


def test_max_reset_codes_per_day_default() -> None:
    settings = Settings()

    assert settings.auth.max_reset_codes_per_day == 10


def test_google_env_vars_land_in_the_google_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-secret")

    settings = Settings()

    assert settings.google.client_id == "client-id.apps.googleusercontent.com"
    assert settings.google.client_secret.get_secret_value() == "google-secret"
    assert settings.google.is_configured
    assert "google-secret" not in repr(settings)


@pytest.mark.parametrize(
    ("client_id", "client_secret"), [("", ""), ("client-id", ""), ("", "google-secret")]
)
def test_google_is_not_configured_without_both_values(
    monkeypatch: pytest.MonkeyPatch, client_id: str, client_secret: str
) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", client_secret)

    assert not Settings().google.is_configured


def test_oauth_state_env_vars_land_in_the_auth_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_OAUTH_STATE_MAX_AGE_SECONDS", "300")
    monkeypatch.setenv("AUTH_OAUTH_STATE_COOKIE_PATH", "/api/v2/auth")

    settings = Settings()

    assert settings.auth.oauth_state_max_age_seconds == 300
    assert settings.auth.oauth_state_cookie_path == "/api/v2/auth"


def test_oauth_state_defaults() -> None:
    settings = Settings()

    assert settings.auth.oauth_state_max_age_seconds == 600
    assert settings.auth.oauth_state_cookie_path == "/api/v1/auth"


def test_media_env_vars_land_in_the_media_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_S3_ENDPOINT_URL", "https://ns.compat.objectstorage.example.com")
    monkeypatch.setenv("MEDIA_REGION", "eu-frankfurt-1")
    monkeypatch.setenv("MEDIA_BUCKET", "backend-showcase-media-dev")
    monkeypatch.setenv("MEDIA_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("MEDIA_SECRET_ACCESS_KEY", "media-secret")
    monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", "https://media.example.com/o/")

    settings = Settings()

    assert settings.media.s3_endpoint_url == "https://ns.compat.objectstorage.example.com"
    assert settings.media.region == "eu-frankfurt-1"
    assert settings.media.bucket == "backend-showcase-media-dev"
    assert settings.media.access_key_id == "access-key"
    assert settings.media.secret_access_key.get_secret_value() == "media-secret"
    assert settings.media.public_base_url == "https://media.example.com/o"
    assert settings.media.can_write
    assert "media-secret" not in repr(settings)


def test_media_cannot_write_without_the_write_keys() -> None:
    assert not Settings().media.can_write


@pytest.mark.parametrize("value", [None, ""])
def test_missing_media_public_base_url_fails(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("MEDIA_PUBLIC_BASE_URL")
    else:
        monkeypatch.setenv("MEDIA_PUBLIC_BASE_URL", value)

    with pytest.raises(ValidationError, match="public_base_url"):
        MediaSettings()  # type: ignore[call-arg]


def test_booking_defaults() -> None:
    booking = Settings().booking

    assert booking.timezone == ZoneInfo("Asia/Tbilisi")
    assert booking.first_slot == time(10, 0)
    assert booking.last_slot == time(21, 30)
    assert booking.slot_minutes == 30
    assert booking.duration_minutes == 90
    assert booking.horizon_days == 30
    assert booking.cancel_cutoff_minutes == 30
    assert booking.max_online_party_size == 4
    assert booking.max_duration_minutes == 180
    assert booking.closing_time == time(23, 0)
    assert booking.preorder_lock_minutes == 30
    assert booking.guest_token_ttl_days == 31
    assert booking.guest_cookie_path == "/"


def test_booking_env_vars_land_in_the_booking_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKING_TIMEZONE", "Europe/Kyiv")
    monkeypatch.setenv("BOOKING_FIRST_SLOT", "09:00")
    monkeypatch.setenv("BOOKING_LAST_SLOT", "22:00")
    monkeypatch.setenv("BOOKING_SLOT_MINUTES", "15")
    monkeypatch.setenv("BOOKING_DURATION_MINUTES", "120")
    monkeypatch.setenv("BOOKING_HORIZON_DAYS", "14")
    monkeypatch.setenv("BOOKING_CANCEL_CUTOFF_MINUTES", "60")
    monkeypatch.setenv("BOOKING_MAX_ONLINE_PARTY_SIZE", "6")
    monkeypatch.setenv("BOOKING_MAX_DURATION_MINUTES", "240")
    monkeypatch.setenv("BOOKING_CLOSING_TIME", "23:30")
    monkeypatch.setenv("BOOKING_PREORDER_LOCK_MINUTES", "45")
    monkeypatch.setenv("BOOKING_GUEST_TOKEN_TTL_DAYS", "7")
    monkeypatch.setenv("BOOKING_GUEST_COOKIE_PATH", "/api/v1")

    booking = Settings().booking

    assert booking.timezone == ZoneInfo("Europe/Kyiv")
    assert booking.first_slot == time(9, 0)
    assert booking.last_slot == time(22, 0)
    assert booking.slot_minutes == 15
    assert booking.duration_minutes == 120
    assert booking.horizon_days == 14
    assert booking.cancel_cutoff_minutes == 60
    assert booking.max_online_party_size == 6
    assert booking.max_duration_minutes == 240
    assert booking.closing_time == time(23, 30)
    assert booking.preorder_lock_minutes == 45
    assert booking.guest_token_ttl_days == 7
    assert booking.guest_cookie_path == "/api/v1"
