import pytest

from app.config.settings import DatabaseSettings, Settings


def test_env_vars_land_in_their_domain_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "custom-name")
    monkeypatch.setenv("DATABASE_HOST", "db.internal")
    monkeypatch.setenv("DATABASE_PORT", "6543")
    monkeypatch.setenv("DATABASE_USER", "svc")
    monkeypatch.setenv("DATABASE_PASSWORD", "s3cret")
    monkeypatch.setenv("DATABASE_NAME", "showcase")

    settings = Settings()

    assert settings.app.name == "custom-name"
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
