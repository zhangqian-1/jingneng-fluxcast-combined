"""Real HTTP prediction transport feeding a real one-period HiGHS solve."""

import json
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import api
from src.forecast_bridge import ForecastClient, ForecastDispatchBridge
from src.renewable_provider import FileRenewableProvider
from src.single_period_service import SinglePeriodService
from tests.test_platform_contract import platform_payload
from tests.test_single_forecast_bridge import payload, prediction


@pytest.fixture
def http_chain(monkeypatch, tmp_path):
    state = {"response": prediction(1000.0), "received": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["received"].append(
                (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            )
            content = state.get("raw", json.dumps(state["response"]).encode())
            self.send_response(state.get("status", 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state["address"] = server.server_address
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    bridge = ForecastDispatchBridge(
        ForecastClient(f"http://127.0.0.1:{server.server_port}"),
        SinglePeriodService(
            tmp_path / "http.sqlite3",
            clock=lambda: datetime(2026, 9, 21, 10, 0, 1, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    try:
        with TestClient(api.app, raise_server_exceptions=False) as client:
            yield client, state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.fixture
def request_only_renewables(http_chain, monkeypatch):
    client, state = http_chain
    connections = []
    connect = socket.socket.connect

    def single_step_only(sock, address):
        connections.append(address)
        if address != state["address"]:
            raise OSError("Unexpected network request; renewable_data must come from the payload")
        return connect(sock, address)

    def reject_file_fallback(*args, **kwargs):
        pytest.fail("Online renewable_data must not fall back to archived forecasts")

    monkeypatch.setattr(socket.socket, "connect", single_step_only)
    monkeypatch.setattr(FileRenewableProvider, "load", reject_file_fallback)
    return client, state, connections


def test_platform_renewables_use_payload_without_external_fetch(request_only_renewables):
    client, state, connections = request_only_renewables
    request = platform_payload()
    for row in request["renewable_data"]:
        if row["farmId"] == 1:
            row["predictedPower"] = 37.5
    response = client.post("/api/v1/fluxcast/compute", json=request)
    assert response.status_code == 200, response.text
    points = {p["varname"]: p["value"] for p in response.json()["result_point"]}
    assert len(points) == 31
    assert points["totalPowerActual"] == 0.0
    assert points["totalPowerForecast"] == 1000.0
    assert points["farm_1_MW"] == 37.5
    assert sum(v for k, v in points.items() if k.endswith("_MW")) == pytest.approx(1000.0)
    assert connections == [state["address"]]
    assert len(state["received"]) == 1
    path, body = state["received"][0]
    assert path == "/api/v1/fluxcast/compute"
    assert set(body) == {"point_table", "frames"}
    assert len(body["frames"]) == 96


@pytest.mark.parametrize("damage", ["missing_field", "empty", "null", "missing_farm"])
def test_invalid_renewables_are_rejected_without_fetch(request_only_renewables, damage):
    client, state, connections = request_only_renewables
    request = platform_payload()
    if damage == "missing_field":
        del request["renewable_data"]
    elif damage == "empty":
        request["renewable_data"] = []
    elif damage == "null":
        request["renewable_data"] = None
    else:
        request["renewable_data"] = [r for r in request["renewable_data"] if r["farmId"] != 29]
    response = client.post("/api/v1/fluxcast/compute", json=request)
    assert response.status_code == 422, response.text
    assert response.json()["event_key"] == "JNH.Fluxcast.Compute"
    assert response.json()["result_point"] == []
    assert connections == []
    assert state["received"] == []


def test_http_prediction_value_is_the_optimized_supply_target(http_chain):
    client, state = http_chain
    request = payload()
    request["forecast_request"]["frames"][0]["JYRD_LOADCTL:GTMWSEL1_1.OUT"] = None
    response = client.post("/api/v1/fluxcast/single-period/compute", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected_demand_mw"] == 1000.0
    assert len(body["result_point"]) == 27
    assert sum(point["value"] for point in body["result_point"]) == pytest.approx(1000.0)
    assert state["received"] == [("/api/v1/fluxcast/compute", request["forecast_request"])]
    assert client.post("/api/v1/fluxcast/single-period/compute", json=request).json() == body
    assert len(state["received"]) == 1


@pytest.mark.parametrize("mode", ["not_ready", "invalid_json", "upstream_error", "wrong_time"])
def test_http_failures_never_publish_zero_or_old_predictions(http_chain, mode):
    client, state = http_chain
    if mode == "not_ready":
        state["response"] = {
            "event_key": "JNH.Fluxcast.Compute",
            "result_point": [],
            "reason": "history_not_ready",
        }
    elif mode == "invalid_json":
        state["raw"] = b"not json"
    elif mode == "upstream_error":
        state["status"] = 503
    else:
        state["response"]["result_point"][0]["timestamp"] = "2026-09-20T10:15:00Z"
    response = client.post("/api/v1/fluxcast/single-period/compute", json=payload())
    assert response.status_code == (202 if mode == "not_ready" else 502)
    assert not response.json().get("result_point")
    assert len(state["received"]) == 1
