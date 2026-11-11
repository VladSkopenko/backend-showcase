import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.error_responses import error_responses
from app.common.errors import DomainError
from app.config.settings import Settings, get_settings
from app.main import create_app

pytestmark = pytest.mark.anyio

AUTH = "/api/v1/auth"
MENU = "/api/v1/menu/dishes"
SERVER_ERROR = {"code": "SERVER_ERROR", "message": "Something went wrong."}


class UnmappedError(DomainError):
    code = "UNMAPPED"

    def __init__(self) -> None:
        super().__init__("Internal details that must not leak.")


@pytest.fixture
def app() -> FastAPI:
    app = create_app()
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
async def client(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.fixture
async def failing_client() -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app()

    @app.get("/test/unhandled")
    async def raise_unhandled() -> None:
        raise RuntimeError("Internal details that must not leak.")

    @app.get("/test/unmapped")
    async def raise_unmapped() -> None:
        raise UnmappedError()

    @app.get("/test/http-500")
    async def raise_http_500() -> None:
        raise HTTPException(status_code=500, detail="Internal details that must not leak.")

    @app.get("/test/teapot")
    async def raise_teapot() -> None:
        raise HTTPException(status_code=418, detail="Internal details that must not leak.")

    # Starlette re-raises an unhandled exception after sending the 500, as uvicorn expects.
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


def registration(**overrides: str) -> dict[str, str]:
    return {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
        "password": "correct-horse",
        "password_confirmation": "correct-horse",
    } | overrides


def reset_confirmation(**overrides: str) -> dict[str, str]:
    return {
        "email": "ada@example.com",
        "code": "123456",
        "password": "correct-horse",
        "password_confirmation": "correct-horse",
    } | overrides


def validation_error(*details: dict[str, str]) -> dict[str, Any]:
    return {"code": "VALIDATION_ERROR", "message": details[0]["message"], "details": list(details)}


async def test_query_out_of_range_names_the_field_without_echoing_input(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.get(MENU, params={"limit": 100})

    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Must be at most 50.",
        "details": [{"field": "limit", "message": "Must be at most 50."}],
    }


async def test_invalid_body_field_gets_a_project_message(client: httpx2.AsyncClient) -> None:
    response = await client.post(f"{AUTH}/register", json=registration(email="x"))

    assert response.status_code == 422
    assert response.json() == validation_error(
        {"field": "email", "message": "Enter a valid email address."}
    )


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/register", registration(password_confirmation="different-pass")),
        ("/password-reset/confirm", reset_confirmation(password_confirmation="different-pass")),
    ],
    ids=["register", "reset-confirm"],
)
async def test_password_mismatch_belongs_to_the_confirmation_field(
    client: httpx2.AsyncClient, path: str, body: dict[str, str]
) -> None:
    response = await client.post(f"{AUTH}{path}", json=body)

    assert response.status_code == 422
    assert response.json() == validation_error(
        {"field": "password_confirmation", "message": "Passwords do not match."}
    )


async def test_short_password_with_the_same_confirmation_reports_only_the_password(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.post(
        f"{AUTH}/register", json=registration(password="short", password_confirmation="short")
    )

    assert response.status_code == 422
    assert response.json() == validation_error(
        {"field": "password", "message": "Must be at least 8 characters."}
    )


async def test_missing_field_is_required(client: httpx2.AsyncClient) -> None:
    response = await client.post(f"{AUTH}/verify-email", json={"email": "ada@example.com"})

    assert response.status_code == 422
    assert response.json() == validation_error(
        {"field": "code", "message": "This field is required."}
    )


@pytest.mark.parametrize(
    ("method", "path", "request_kwargs", "detail"),
    [
        (
            "post",
            f"{AUTH}/register",
            {"json": registration(first_name="x" * 101)},
            {"field": "first_name", "message": "Must be at most 100 characters."},
        ),
        (
            "post",
            f"{AUTH}/register",
            {"json": registration(first_name=" ")},
            {"field": "first_name", "message": "This field is required."},
        ),
        (
            "post",
            f"{AUTH}/verify-email",
            {"json": {"email": "ada@example.com", "code": "abcdef"}},
            {"field": "code", "message": "Has an invalid format."},
        ),
        (
            "get",
            MENU,
            {"params": {"limit": 0}},
            {"field": "limit", "message": "Must be at least 1."},
        ),
        (
            "get",
            MENU,
            {"params": {"sort": "CHEAPEST"}},
            {"field": "sort", "message": "Has an invalid value."},
        ),
    ],
    ids=["too-long", "blank", "pattern", "below-minimum", "unknown-enum-value"],
)
async def test_validation_messages_are_project_texts(
    client: httpx2.AsyncClient,
    method: str,
    path: str,
    request_kwargs: dict[str, Any],
    detail: dict[str, str],
) -> None:
    response = await client.request(method.upper(), path, **request_kwargs)

    assert response.status_code == 422
    assert response.json() == validation_error(detail)


async def test_several_errors_keep_field_order_and_lead_with_the_first(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.post(f"{AUTH}/register", json={})

    assert response.status_code == 422
    body = response.json()
    assert [detail["field"] for detail in body["details"]] == [
        "first_name",
        "last_name",
        "email",
        "password",
        "password_confirmation",
    ]
    assert body["message"] == body["details"][0]["message"]


async def test_malformed_json_has_no_field(client: httpx2.AsyncClient) -> None:
    response = await client.post(
        f"{AUTH}/login", content=b"{bad", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json() == validation_error({"message": "Request body is not valid JSON."})


async def test_empty_body_is_required(client: httpx2.AsyncClient) -> None:
    response = await client.post(f"{AUTH}/login")

    assert response.status_code == 422
    assert response.json() == validation_error({"message": "Request body is required."})


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"json": [{"email": "ada@example.com", "password": "correct-horse"}]},
        {"content": b"hello", "headers": {"content-type": "text/plain"}},
    ],
    ids=["json-array", "text-plain"],
)
async def test_body_that_is_not_an_object_has_no_field(
    client: httpx2.AsyncClient, request_kwargs: dict[str, Any]
) -> None:
    response = await client.post(f"{AUTH}/login", **request_kwargs)

    assert response.status_code == 422
    assert response.json() == validation_error({"message": "Request body must be a JSON object."})


async def test_bad_path_uuid_names_the_parameter(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"{MENU}/abc")

    assert response.status_code == 422
    assert response.json() == validation_error(
        {"field": "dish_id", "message": "Has an invalid format."}
    )


async def test_unknown_route_is_not_found(client: httpx2.AsyncClient) -> None:
    response = await client.get("/nope")

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Not found."}


async def test_wrong_method_keeps_the_allow_header(client: httpx2.AsyncClient) -> None:
    response = await client.delete(MENU)

    assert response.status_code == 405
    assert response.json() == {"code": "METHOD_NOT_ALLOWED", "message": "Method not allowed."}
    assert response.headers["allow"] == "GET"


async def test_unknown_oauth_provider_is_not_found(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"{AUTH}/yahoo/login")

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Not found."}


async def test_other_http_errors_use_the_status_phrase(
    failing_client: httpx2.AsyncClient,
) -> None:
    response = await failing_client.get("/test/teapot")

    assert response.status_code == 418
    assert response.json() == {"code": "HTTP_ERROR", "message": "I'm a Teapot."}


async def test_unhandled_exception_is_a_generic_500(
    failing_client: httpx2.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = await failing_client.get("/test/unhandled")

    assert response.status_code == 500
    assert response.json() == SERVER_ERROR
    # The server logs the re-raised exception; the app must not log it a second time.
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


async def test_http_500_is_the_generic_server_error(
    failing_client: httpx2.AsyncClient,
) -> None:
    response = await failing_client.get("/test/http-500")

    assert response.status_code == 500
    assert response.json() == SERVER_ERROR


async def test_unmapped_domain_error_is_a_generic_500_logged_with_traceback(
    failing_client: httpx2.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = await failing_client.get("/test/unmapped")

    assert response.status_code == 500
    assert response.json() == SERVER_ERROR
    [record] = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], UnmappedError)
    assert record.exc_info[2] is not None


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return create_app().openapi()


def test_openapi_has_no_fastapi_validation_schema(schema: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in json.dumps(schema)
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert "ErrorResponse" in schema["components"]["schemas"]


def test_documented_client_errors_use_the_shared_schema(schema: dict[str, Any]) -> None:
    client_errors = [
        (path, method, status, response)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        for status, response in operation["responses"].items()
        if status.startswith("4")
    ]

    assert client_errors
    for path, method, status, response in client_errors:
        assert response["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }, (method, path, status)


def test_dish_lookup_documents_its_errors(schema: dict[str, Any]) -> None:
    responses = schema["paths"][f"{MENU}/{{dish_id}}"]["get"]["responses"]

    assert "DISH_NOT_FOUND" in responses["404"]["description"]
    assert "VALIDATION_ERROR" in responses["422"]["description"]


def test_health_keeps_its_own_503_body(schema: dict[str, Any]) -> None:
    responses = schema["paths"]["/health"]["get"]["responses"]

    assert responses["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }


def test_documenting_an_error_without_a_status_fails_fast() -> None:
    with pytest.raises(ValueError, match="UnmappedError"):
        error_responses(UnmappedError, statuses={}, takes_input=False)
