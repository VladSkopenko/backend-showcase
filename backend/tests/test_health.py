from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_lists_health_schema() -> None:
    with TestClient(create_app()) as client:
        spec = client.get("/openapi.json").json()

    response_schema = spec["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"] == "#/components/schemas/HealthResponse"
    status = spec["components"]["schemas"]["HealthResponse"]["properties"]["status"]
    assert status.get("const") == "ok" or status.get("enum") == ["ok"]
    assert spec["info"]["title"] == "backend-showcase"
