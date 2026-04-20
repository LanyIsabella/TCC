from fastapi.testclient import TestClient
from src.api.main import create_app


def test_healthcheck_returns_application_metadata() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_name": "TCC Sistema Agent API",
        "version": "0.1.0",
    }
