from fastapi.testclient import TestClient
from kumi.core.api.app_factory import app
from kumi.core.features.proactive.timer_tools import ACTIVE_TIMERS


def test_list_timers_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr("kumi.core.features.proactive.timer_tools._SCHEDULES_PATH", tmp_path / "schedules.json")
    ACTIVE_TIMERS.clear()
    ACTIVE_TIMERS["abc123"] = {
        "id": "abc123",
        "type": "scheduled",
        "description": "daily check",
        "owner_user_id": "_local",
        "next_fire_at": "2026-05-14T09:00:00",
    }

    response = TestClient(app).get("/timers")

    assert response.status_code == 200
    assert response.json()["timers"][0]["id"] == "abc123"


def test_cancel_timer_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr("kumi.core.features.proactive.timer_tools._SCHEDULES_PATH", tmp_path / "schedules.json")
    ACTIVE_TIMERS.clear()
    ACTIVE_TIMERS["abc123"] = {
        "id": "abc123",
        "type": "scheduled",
        "description": "daily check",
        "owner_user_id": "_local",
        "next_fire_at": "2026-05-14T09:00:00",
    }

    response = TestClient(app).delete("/timers/abc123")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert "abc123" not in ACTIVE_TIMERS
