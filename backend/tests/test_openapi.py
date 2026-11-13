from typing import Any

import pytest

from app.main import app

FLOWS = {
    "Registration": [
        ("post", "/api/v1/auth/register"),
        ("post", "/api/v1/auth/verify-email"),
        ("post", "/api/v1/auth/resend-code"),
    ],
    "Password reset": [
        ("post", "/api/v1/auth/password-reset/request"),
        ("post", "/api/v1/auth/password-reset/verify-code"),
        ("post", "/api/v1/auth/password-reset/confirm"),
    ],
    "Session": [
        ("post", "/api/v1/auth/login"),
        ("post", "/api/v1/auth/refresh"),
        ("post", "/api/v1/auth/logout"),
        ("get", "/api/v1/auth/me"),
    ],
    "OAuth sign-in": [
        ("get", "/api/v1/auth/{provider_slug}/login"),
        ("get", "/api/v1/auth/{provider_slug}/callback"),
    ],
    "Menu": [
        ("get", "/api/v1/menu/dishes"),
        ("get", "/api/v1/menu/dishes/{dish_id}"),
    ],
    "Locations": [
        ("get", "/api/v1/locations"),
        ("get", "/api/v1/locations/{location_id}"),
    ],
    "Booking": [
        ("get", "/api/v1/bookings/tables"),
        ("post", "/api/v1/bookings"),
        ("get", "/api/v1/bookings"),
        ("post", "/api/v1/bookings/{booking_id}/cancel"),
        ("put", "/api/v1/bookings/{booking_id}"),
        ("get", "/api/v1/bookings/{booking_id}/slots"),
        ("get", "/api/v1/bookings/{booking_id}"),
    ],
    "Invites": [
        ("get", "/api/v1/bookings/{booking_id}/invite"),
        ("get", "/api/v1/invites/{code}"),
        ("post", "/api/v1/invites/{code}/join"),
    ],
    "Pre-order": [
        ("get", "/api/v1/bookings/{booking_id}/cart"),
        ("put", "/api/v1/bookings/{booking_id}/cart/items/{dish_id}"),
        ("delete", "/api/v1/bookings/{booking_id}/cart/items/{dish_id}"),
        ("post", "/api/v1/bookings/{booking_id}/cart/submit"),
        ("get", "/api/v1/bookings/{booking_id}/my-pre-order"),
    ],
    "Staff": [
        ("get", "/api/v1/staff/booking-requests"),
        ("post", "/api/v1/staff/booking-requests/{booking_id}/approve"),
        ("post", "/api/v1/staff/booking-requests/{booking_id}/reject"),
    ],
    "Notifications": [
        ("get", "/api/v1/notifications"),
        ("post", "/api/v1/notifications/{notification_id}/read"),
    ],
    "Health": [
        ("get", "/"),
        ("get", "/health"),
    ],
}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return app.openapi()


def test_tags_follow_the_user_flows_in_order_with_descriptions(schema: dict[str, Any]) -> None:
    tags = schema["tags"]

    assert [tag["name"] for tag in tags] == list(FLOWS)
    assert all(tag["description"] for tag in tags)


@pytest.mark.parametrize(
    ("tag", "method", "path"),
    [(tag, method, path) for tag, routes in FLOWS.items() for method, path in routes],
)
def test_every_route_sits_in_its_flow_with_a_description(
    schema: dict[str, Any], tag: str, method: str, path: str
) -> None:
    operation = schema["paths"][path][method]

    assert operation["tags"] == [tag]
    assert operation["description"]


def test_every_documented_route_belongs_to_a_flow(schema: dict[str, Any]) -> None:
    documented = {
        (method, path) for path, operations in schema["paths"].items() for method in operations
    }

    assert documented == {route for routes in FLOWS.values() for route in routes}


def test_oauth_routes_say_they_are_browser_navigations(schema: dict[str, Any]) -> None:
    for _, path in FLOWS["OAuth sign-in"]:
        assert "never" in schema["paths"][path]["get"]["description"]
        assert "fetch" in schema["paths"][path]["get"]["description"]


def test_provider_slug_lists_the_known_providers(schema: dict[str, Any]) -> None:
    for _, path in FLOWS["OAuth sign-in"]:
        (parameter,) = schema["paths"][path]["get"]["parameters"]

        assert parameter["name"] == "provider_slug"
        assert parameter["schema"]["enum"] == ["google"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/bookings/{booking_id}"),
        ("post", "/api/v1/invites/{code}/join"),
        *FLOWS["Pre-order"],
    ],
)
def test_guest_routes_mention_the_guest_cookie(
    schema: dict[str, Any], method: str, path: str
) -> None:
    assert "`guest_token`" in schema["paths"][path][method]["description"]
