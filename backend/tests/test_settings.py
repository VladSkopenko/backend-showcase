import pytest

from app.config.settings import DatabaseSettings, Settings


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
    assert settings.database.host == "db.internal"
    assert settings.database.port == 6543
    assert settings.database.user == "svc"
    assert settings.database.password.get_secret_value() == "s3cret"
    assert settings.database.name == "showcase"


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
