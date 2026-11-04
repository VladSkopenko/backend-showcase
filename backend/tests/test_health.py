from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_lists_health_schema() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "backend-showcase"
    health_200 = spec["paths"]["/health"]["get"]["responses"]["200"]
    schema_ref = health_200["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref == "#/components/schemas/HealthResponse"
    status = spec["components"]["schemas"]["HealthResponse"]["properties"]["status"]
    assert status["const"] == "ok"
