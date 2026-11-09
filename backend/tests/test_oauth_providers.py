from typing import Any

import pytest

from app.features.core.auth.dto import OAuthIdentity
from app.features.core.auth.services.exceptions import OAuthFailedError
from app.features.core.auth.services.oauth_providers import GoogleOAuthProvider

CLAIMS: dict[str, Any] = {
    "sub": "1234567890",
    "email": "ada@example.com",
    "email_verified": True,
    "given_name": "Ada",
    "family_name": "Lovelace",
    "name": "Ada Lovelace",
}


def identity(**overrides: Any) -> OAuthIdentity:
    claims = {**CLAIMS, **overrides}
    claims = {key: value for key, value in claims.items() if value is not None}
    return GoogleOAuthProvider(is_configured=True).identity(claims=claims)


def test_google_claims_become_an_identity() -> None:
    assert identity() == OAuthIdentity(
        subject="1234567890",
        email="ada@example.com",
        email_verified=True,
        first_name="Ada",
        last_name="Lovelace",
    )


def test_missing_given_name_falls_back_to_name() -> None:
    assert identity(given_name=None).first_name == "Ada Lovelace"


def test_missing_given_name_and_name_fall_back_to_the_email_local_part() -> None:
    assert identity(given_name=None, name=None).first_name == "ada"


def test_missing_given_name_name_and_email_give_an_empty_first_name() -> None:
    result = identity(given_name=None, name=None, email=None)

    assert result.first_name == ""
    assert result.email is None


def test_missing_family_name_is_an_empty_string() -> None:
    assert identity(family_name=None).last_name == ""


def test_names_are_cut_to_100_characters() -> None:
    result = identity(given_name="a" * 150, family_name="b" * 101)

    assert result.first_name == "a" * 100
    assert result.last_name == "b" * 100


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        ("true", True),
        (False, False),
        ("false", False),
        ("True", False),
        (1, False),
        ("1", False),
        (None, False),
    ],
)
def test_email_verified_is_true_only_for_json_true_or_the_string_true(
    value: Any, expected: bool
) -> None:
    assert identity(email_verified=value).email_verified is expected


@pytest.mark.parametrize("subject", [None, "", 123])
def test_missing_or_invalid_sub_fails(subject: Any) -> None:
    with pytest.raises(OAuthFailedError):
        identity(sub=subject)
