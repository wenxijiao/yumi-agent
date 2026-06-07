"""Health endpoint integration tests (OSS single-user)."""

from fastapi.testclient import TestClient
from kumi.core.api import app


def test_health_returns_status_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["identity_user_id"] == "_local"
