import pytest
from fastapi.testclient import TestClient

import api


def test_health_reports_single_period_service():
    response = TestClient(api.app).get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "single_period"


@pytest.mark.parametrize(
    "path",
    [
        "/compute",
        "/api/v1/fluxcast/rolling/actuals",
        "/api/v1/fluxcast/rolling/reference-plan",
        "/api/v1/fluxcast/rolling/forecasts/demand",
        "/api/v1/fluxcast/rolling/forecasts/renewable",
    ],
)
def test_removed_optimization_routes_cannot_run(path):
    client = TestClient(api.app)
    assert client.post(path, json={}).status_code == 404
    assert path not in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/fluxcast/rolling/status/old",
        "/api/v1/fluxcast/rolling/dashboard",
        "/api/v1/fluxcast/dashboard-result",
    ],
)
def test_removed_result_routes_are_unavailable(path):
    assert TestClient(api.app).get(path).status_code == 404


def test_openapi_has_only_current_contract():
    paths = TestClient(api.app).get("/openapi.json").json()["paths"]
    assert set(paths) == {
        "/health",
        "/api/v1/fluxcast/config/prices",
        "/api/v1/fluxcast/compute",
        "/api/v1/fluxcast/forecast/compute",
        "/api/v1/fluxcast/forecast/latest",
        "/api/v1/fluxcast/single-period/compute",
        "/api/v1/fluxcast/single-period/status/{snapshot_id}",
    }


def test_bridge_reuses_service_and_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("SINGLE_PERIOD_DB_PATH", str(tmp_path / "single.sqlite3"))
    api.get_forecast_bridge.cache_clear()
    try:
        assert api.get_forecast_bridge() is api.get_forecast_bridge()
    finally:
        api.get_forecast_bridge.cache_clear()


@pytest.mark.parametrize(
    "name,value", [("FORECAST_BASE_URL", "not-a-url"), ("DISPATCH_DAY_TIMEZONE", "not-a-zone")]
)
def test_invalid_service_configuration_is_sanitized(monkeypatch, tmp_path, name, value):
    monkeypatch.setenv("SINGLE_PERIOD_DB_PATH", str(tmp_path / "single.sqlite3"))
    monkeypatch.setenv(name, value)
    api.get_forecast_bridge.cache_clear()
    try:
        response = TestClient(api.app, raise_server_exceptions=False).get(
            "/api/v1/fluxcast/forecast/latest"
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "SINGLE_PERIOD_CONFIGURATION_ERROR"
        assert value not in response.text
    finally:
        api.get_forecast_bridge.cache_clear()


def test_validation_failures_are_logged_and_log_failure_is_explicit(monkeypatch, tmp_path):
    client = TestClient(api.app, raise_server_exceptions=False)
    assert client.post("/api/v1/fluxcast/single-period/compute", json={}).status_code == 422
    assert "REQUEST_VALIDATION_ERROR" in (tmp_path / "work.jsonl").read_text("utf-8")
    assert (
        client.post(
            "/api/v1/fluxcast/single-period/compute",
            content="{",
            headers={"Content-Type": "application/json"},
        ).status_code
        == 400
    )
    monkeypatch.setenv("WORK_LOG_PATH", str(tmp_path))
    result = client.post("/api/v1/fluxcast/single-period/compute", json={})
    assert result.status_code == 503
    assert result.json()["error_code"] == "WORK_LOG_UNAVAILABLE"
