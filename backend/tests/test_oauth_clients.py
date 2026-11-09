import base64
import hashlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.config.settings import GoogleSettings
from app.features.core.auth.enums import OAuthProvider
from app.infrastructure.oauth import OAuthClients, OAuthExchangeError

pytestmark = pytest.mark.anyio

CLIENT_ID = "client-id.apps.googleusercontent.com"
ISSUER = "https://accounts.example"
AUTHORIZE_URL = f"{ISSUER}/authorize"
TOKEN_URL = f"{ISSUER}/token"
REDIRECT_URI = "https://front.example/api/v1/auth/google/callback"
SIGNING_KEY = RSAKey.generate_key(2048, parameters={"kid": "signing"}, private=True)
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "signing"}, private=True)


@dataclass
class FakeGoogle:
    """Token endpoint behind an httpx2.MockTransport; signs an ID token for the authorize nonce."""

    nonce: str | None = None
    code_challenge: str | None = None
    key: RSAKey = field(default_factory=lambda: SIGNING_KEY)
    include_id_token: bool = True
    token_requests: list[dict[str, list[str]]] = field(default_factory=list)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == TOKEN_URL
        form = parse_qs(request.content.decode())
        self.token_requests.append(form)
        verifier = form["code_verifier"][0]
        digest = hashlib.sha256(verifier.encode()).digest()
        assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == self.code_challenge
        body: dict[str, Any] = {
            "access_token": "access",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        if self.include_id_token:
            now = int(time.time())
            claims = {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "sub": "google-sub-1",
                "email": "ada@example.com",
                "email_verified": True,
                "nonce": self.nonce,
                "iat": now,
                "exp": now + 3600,
            }
            body["id_token"] = jwt.encode({"alg": "RS256", "kid": "signing"}, claims, self.key)
        return httpx2.Response(200, json=body)


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def clients(google: FakeGoogle) -> OAuthClients:
    return OAuthClients(
        google=GoogleSettings(client_id=CLIENT_ID, client_secret=SecretStr("client-secret")),
        server={
            "google": {
                "issuer": ISSUER,
                "authorize_url": AUTHORIZE_URL,
                "access_token_url": TOKEN_URL,
                "jwks": {"keys": [SIGNING_KEY.as_dict(private=False)]},
            }
        },
        client_kwargs={"transport": httpx2.MockTransport(google.handle)},
    )


def build_app(clients: OAuthClients) -> Starlette:
    async def login(request: Request) -> Response:
        try:
            return await clients.authorize_redirect(
                request=request, provider_slug="google", redirect_uri=REDIRECT_URI
            )
        except OAuthExchangeError as failure:
            return JSONResponse({"failed": True, "cancelled": failure.cancelled})

    async def callback(request: Request) -> Response:
        try:
            claims = await clients.fetch_claims(request=request, provider_slug="google")
        except OAuthExchangeError as failure:
            return JSONResponse({"failed": True, "cancelled": failure.cancelled})
        return JSONResponse({"failed": False, "claims": claims})

    return Starlette(
        routes=[Route("/login", login), Route("/callback", callback)],
        middleware=[
            Middleware(
                SessionMiddleware,
                secret_key="test-secret",
                session_cookie="oauth_state",
                https_only=True,
            )
        ],
    )


@pytest.fixture
async def client(clients: OAuthClients) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=build_app(clients))
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


async def start(client: httpx2.AsyncClient, google: FakeGoogle) -> dict[str, str]:
    response = await client.get("/login")
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == AUTHORIZE_URL
    query = {key: values[0] for key, values in parse_qs(location.query).items()}
    google.nonce = query["nonce"]
    google.code_challenge = query["code_challenge"]
    return query


def state_cookie_deleted(response: httpx2.Response) -> bool:
    return any(
        header.startswith("oauth_state=null;") and "01 Jan 1970" in header
        for header in response.headers.get_list("set-cookie")
    )


async def test_authorize_url_carries_state_nonce_pkce_and_the_redirect_uri(
    client: httpx2.AsyncClient, google: FakeGoogle
) -> None:
    query = await start(client, google)

    assert query["client_id"] == CLIENT_ID
    assert query["response_type"] == "code"
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["scope"] == "openid email profile"
    assert query["code_challenge_method"] == "S256"
    assert query["state"]
    assert query["nonce"]
    assert "oauth_state" in client.cookies


async def test_callback_returns_the_validated_id_token_claims(
    client: httpx2.AsyncClient, google: FakeGoogle
) -> None:
    query = await start(client, google)

    response = await client.get("/callback", params={"code": "auth-code", "state": query["state"]})

    body = response.json()
    assert body["failed"] is False, body
    assert body["claims"]["sub"] == "google-sub-1"
    assert body["claims"]["email"] == "ada@example.com"
    assert body["claims"]["email_verified"] is True
    [form] = google.token_requests
    assert form["redirect_uri"] == [REDIRECT_URI]
    assert form["code"] == ["auth-code"]
    assert state_cookie_deleted(response)


async def test_state_mismatch_fails(client: httpx2.AsyncClient, google: FakeGoogle) -> None:
    await start(client, google)

    response = await client.get("/callback", params={"code": "auth-code", "state": "forged"})

    assert response.json() == {"failed": True, "cancelled": False}
    assert google.token_requests == []
    assert state_cookie_deleted(response)


async def test_missing_state_cookie_fails(client: httpx2.AsyncClient, google: FakeGoogle) -> None:
    query = await start(client, google)
    client.cookies.clear()

    response = await client.get("/callback", params={"code": "auth-code", "state": query["state"]})

    assert response.json() == {"failed": True, "cancelled": False}
    assert google.token_requests == []


async def test_access_denied_is_cancelled(client: httpx2.AsyncClient, google: FakeGoogle) -> None:
    query = await start(client, google)

    response = await client.get(
        "/callback", params={"error": "access_denied", "state": query["state"]}
    )

    assert response.json() == {"failed": True, "cancelled": True}
    assert state_cookie_deleted(response)


async def test_missing_id_token_fails(client: httpx2.AsyncClient, google: FakeGoogle) -> None:
    google.include_id_token = False
    query = await start(client, google)

    response = await client.get("/callback", params={"code": "auth-code", "state": query["state"]})

    assert response.json() == {"failed": True, "cancelled": False}
    assert state_cookie_deleted(response)


async def test_id_token_with_a_bad_signature_fails(
    client: httpx2.AsyncClient, google: FakeGoogle
) -> None:
    google.key = OTHER_KEY
    query = await start(client, google)

    response = await client.get("/callback", params={"code": "auth-code", "state": query["state"]})

    assert response.json() == {"failed": True, "cancelled": False}
    assert state_cookie_deleted(response)


async def test_unconfigured_provider_fails_without_a_state_cookie() -> None:
    clients = OAuthClients(google=GoogleSettings(client_id="", client_secret=SecretStr("")))
    transport = httpx2.ASGITransport(app=build_app(clients))
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/login")

    assert response.json() == {"failed": True, "cancelled": False}
    assert "oauth_state" not in client.cookies


def test_the_google_client_is_registered_under_the_provider_slug() -> None:
    assert OAuthClients.GOOGLE_SLUG == OAuthProvider.GOOGLE.slug
