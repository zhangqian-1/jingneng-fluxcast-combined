"""Forecast packaging boundary: one solve, no vendor edits, no stale/zero fallback."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api
from src.errors import DispatchServiceError
from src.forecast_bridge import (
    DEMAND_BASIS,
    EVENT_KEY,
    ForecastDispatchBridge,
    SingleComputePayload,
    select_target_prediction,
)
from src.single_period_models import ActualSnapshot
from src.single_period_service import SinglePeriodService
from tests.single_helpers import complete_actual, forecasts


def payload():
    actual = complete_actual()
    renewable = forecasts(actual)["renewable"]
    renewable["frames"] = renewable["frames"][:1]
    timestamp = datetime.fromisoformat(actual["timestamp"])
    return {
        "actual": actual,
        "renewable_forecast": renewable,
        "forecast_request": {
            "point_table": ["JYRD_LOADCTL:GTMWSEL1_1.OUT"],
            "frames": [
                {
                    "timestamp": (timestamp - timedelta(minutes=15 * n)).isoformat(),
                    "JYRD_LOADCTL:GTMWSEL1_1.OUT": 1.23,
                }
                for n in reversed(range(96))
            ],
        },
    }


def prediction(value=1000.0, count=1):
    start = datetime.fromisoformat(complete_actual()["timestamp"]) + timedelta(minutes=15)
    return {
        "event_key": EVENT_KEY,
        "result_point": [
            {
                "timestamp": (start + n * timedelta(minutes=15)).isoformat(),
                "varname": "totalPowerForecast",
                "value": value + n,
            }
            for n in range(count)
        ],
    }


class Upstream:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, body=None):
        self.calls.append(deepcopy(body))
        return 200, deepcopy(self.response)


@pytest.fixture
def bridge_client(monkeypatch, tmp_path):
    upstream = Upstream(prediction())
    service = SinglePeriodService(
        tmp_path / "single.sqlite3",
        clock=lambda: datetime(2026, 9, 21, 10, 0, 1, tzinfo=timezone.utc),
    )
    bridge = ForecastDispatchBridge(upstream, service)
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    with TestClient(api.app) as client:
        yield client, upstream, bridge


def test_true_one_step_solver_and_persisted_forecast_provenance(bridge_client):
    client, upstream, bridge = bridge_client
    body = payload()
    response = client.post("/api/v1/fluxcast/single-period/compute", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["horizon_steps"] == result["publish_steps"] == 1
    assert result["selected_demand_mw"] == 1000.0
    assert result["demand_basis"] == DEMAND_BASIS
    assert result["comparison"]["status"] == "not_provided"
    assert len(result["result_point"]) == 27
    assert sum(p["value"] for p in result["result_point"]) == pytest.approx(1000.0)
    assert all(type(p["value"]) is float for p in result["result_point"])
    assert all(p["value"] >= 0.0 for p in result["result_point"])
    assert upstream.calls == [body["forecast_request"]]
    repeated = client.post("/api/v1/fluxcast/single-period/compute", json=body)
    assert repeated.json() == result
    assert len(upstream.calls) == 1
    assert client.get("/api/v1/fluxcast/single-period/status/measured-001").json() == result
    with bridge.dispatch.store.connection() as db:
        inputs = bridge.dispatch.store.inputs(db, "measured-001")
    assert len(inputs["demand_forecast"]["frames"]) == 1
    assert len(inputs["renewable_forecast"]["frames"]) == 1


@pytest.mark.parametrize("reason", ["history_not_ready", "weather_history_not_ready"])
def test_warmup_waits_without_publishing_or_reading_latest(bridge_client, reason):
    client, upstream, bridge = bridge_client
    upstream.response = {"event_key": EVENT_KEY, "result_point": [], "reason": reason}
    response = client.post("/api/v1/fluxcast/single-period/compute", json=payload())
    assert response.status_code == 202
    assert response.json()["status"] == "waiting_forecast"
    assert response.json()["result_point"] == []
    assert (
        client.get("/api/v1/fluxcast/single-period/status/measured-001").json() == response.json()
    )
    assert all(call is not None for call in upstream.calls)
    with bridge.dispatch.store.connection() as db:
        assert bridge.dispatch.store.result(db, "measured-001") is None
    upstream.response = prediction()
    assert client.post("/api/v1/fluxcast/single-period/compute", json=payload()).status_code == 200


@pytest.mark.parametrize("change", ["history", "renewable"])
def test_completed_input_cannot_be_replaced(bridge_client, change):
    client, _, _ = bridge_client
    body = payload()
    assert client.post("/api/v1/fluxcast/single-period/compute", json=body).status_code == 200
    if change == "history":
        body["forecast_request"]["frames"][0]["JYRD_LOADCTL:GTMWSEL1_1.OUT"] = 123.0
    else:
        body["renewable_forecast"]["frames"][0]["power_mw"]["1"] = 9.0
    assert client.post("/api/v1/fluxcast/single-period/compute", json=body).status_code == 409


@pytest.mark.parametrize("damage", ["stale", "missing", "nan", "boolean", "name", "negative"])
def test_bad_vendor_result_is_never_zero_filled(damage):
    response = prediction()
    if damage == "stale":
        response["result_point"][0]["timestamp"] = "2026-09-21T10:00:00Z"
    elif damage == "missing":
        response["result_point"].pop()
    elif damage == "name":
        response["result_point"][0]["varname"] = "different"
    else:
        response["result_point"][0]["value"] = {
            "nan": float("nan"),
            "boolean": True,
            "negative": -1.0,
        }[damage]
    with pytest.raises(DispatchServiceError):
        select_target_prediction(response, ActualSnapshot.model_validate(complete_actual()))


def test_input_axis_and_state_are_required():
    body = payload()
    body["actual"].pop("thermal_state")
    with pytest.raises(ValidationError):
        SingleComputePayload.model_validate(body)
    body = payload()
    body["forecast_request"]["frames"].pop()
    with pytest.raises(ValidationError):
        SingleComputePayload.model_validate(body)


def test_proxy_preserves_raw_point_names_and_null(bridge_client):
    client, upstream, _ = bridge_client
    raw = payload()["forecast_request"]
    raw["frames"][0]["JYRD_LOADCTL:GTMWSEL1_1.OUT"] = None
    result = client.post("/api/v1/fluxcast/forecast/compute", json=raw)
    assert result.status_code == 200
    assert upstream.calls == [raw]
    assert result.json() == upstream.response


def test_optional_one_period_reference_does_not_resolve(bridge_client, monkeypatch):
    client, _, bridge = bridge_client
    body = payload()
    result = client.post("/api/v1/fluxcast/single-period/compute", json=body).json()
    points = {p["varname"]: p["value"] for p in result["result_point"]}
    actual = body["actual"]
    body["reference_plan"] = {
        "snapshot_id": actual["snapshot_id"],
        "plan_id": "original-test-plan",
        "issued_at": actual["timestamp"],
        "frames": [
            {
                "timestamp": result["effective_at"],
                "thermal_mw": {c: points[c + "_MW"] for c in actual["thermal_mw"]},
                "thermal_running": result["thermal_running"],
                "renewable_mw": {f: points[f"farm_{f}_MW"] for f in actual["renewable_mw"]},
                "grid_buy_mw": points["grid_buy_MW"],
            }
        ],
    }
    monkeypatch.setattr(bridge.dispatch, "_solve", lambda _: pytest.fail("must not solve again"))
    response = client.post("/api/v1/fluxcast/single-period/compute", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["comparison"]["status"] == "available"
    assert response.json()["result_point"] == result["result_point"]
    assert response.json()["comparison"]["step_metrics"]["costSavingYuan"] == pytest.approx(0.0)


def test_expired_actual_never_calls_forecast(bridge_client):
    client, upstream, bridge = bridge_client
    bridge.dispatch.clock = lambda: datetime(2026, 9, 21, 10, 15, tzinfo=timezone.utc)
    response = client.post("/api/v1/fluxcast/single-period/compute", json=payload())
    assert response.status_code == 409
    assert not upstream.calls


@pytest.mark.parametrize("damage", ["duplicate", "reverse", "gap", "eight_frames"])
def test_malformed_history_is_rejected_before_upstream(bridge_client, damage):
    client, upstream, _ = bridge_client
    body = payload()
    history = body["forecast_request"]["frames"]
    if damage == "duplicate":
        history[0]["timestamp"] = history[1]["timestamp"]
    elif damage == "reverse":
        history.reverse()
    elif damage == "gap":
        history[1]["timestamp"] = "2026-09-20T00:00:00Z"
    else:
        body["renewable_forecast"]["frames"] *= 8
    assert client.post("/api/v1/fluxcast/single-period/compute", json=body).status_code == 422
    assert not upstream.calls


def test_parallel_retries_call_prediction_and_solve_once(bridge_client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    client, upstream, bridge = bridge_client
    original = bridge.dispatch._solve
    calls = []

    def counted(inputs):
        calls.append(inputs)
        return original(inputs)

    monkeypatch.setattr(bridge.dispatch, "_solve", counted)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(client.post, "/api/v1/fluxcast/single-period/compute", json=payload())
            for _ in range(2)
        ]
        responses = [future.result() for future in futures]
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert len(upstream.calls) == len(calls) == 1


def test_predictor_finishing_after_deadline_does_not_solve(bridge_client, monkeypatch):
    client, upstream, bridge = bridge_client
    request = upstream.request

    def late(body):
        bridge.dispatch.clock = lambda: datetime(2026, 9, 21, 10, 15, tzinfo=timezone.utc)
        return request(body)

    monkeypatch.setattr(upstream, "request", late)
    monkeypatch.setattr(bridge.dispatch, "_solve", lambda _: pytest.fail("expired forecast solved"))
    response = client.post("/api/v1/fluxcast/single-period/compute", json=payload())
    assert response.status_code == 409
    assert not response.json().get("result_point")


def test_accounting_finishing_after_deadline_cannot_publish(bridge_client, monkeypatch):
    client, _, bridge = bridge_client
    compare = bridge.dispatch._compare

    def late(inputs, archive):
        compare(inputs, archive)
        bridge.dispatch.clock = lambda: datetime(2026, 9, 21, 10, 15, tzinfo=timezone.utc)

    monkeypatch.setattr(bridge.dispatch, "_compare", late)
    response = client.post("/api/v1/fluxcast/single-period/compute", json=payload())
    assert response.status_code == 409
    with bridge.dispatch.store.connection() as db:
        assert bridge.dispatch.store.result(db, "measured-001") is None


def test_unbalanced_optional_plan_does_not_block_optimization(bridge_client):
    client, _, _ = bridge_client
    body = payload()
    actual = body["actual"]
    body["reference_plan"] = {
        "snapshot_id": actual["snapshot_id"],
        "plan_id": "unbalanced",
        "issued_at": actual["timestamp"],
        "frames": [
            {
                "timestamp": body["renewable_forecast"]["frames"][0]["timestamp"],
                "thermal_mw": actual["thermal_mw"],
                "thermal_running": dict.fromkeys(actual["thermal_mw"], False),
                "renewable_mw": dict.fromkeys(actual["renewable_mw"], 0.0),
                "grid_buy_mw": 0.0,
            }
        ],
    }
    response = client.post("/api/v1/fluxcast/single-period/compute", json=body)
    assert response.status_code == 200
    assert response.json()["comparison"]["status"] == "unavailable"
    assert len(response.json()["result_point"]) == 27


def test_state_history_cannot_omit_today_start(bridge_client):
    client, upstream, _ = bridge_client
    body = payload()
    body["actual"]["thermal_mw"]["GARD"] = 125.0
    body["actual"]["thermal_state"]["GARD"].update(
        running=True, state_since="2026-09-21T09:45:00Z", starts_today=0
    )
    assert client.post("/api/v1/fluxcast/single-period/compute", json=body).status_code == 422
    assert not upstream.calls


def test_infeasible_supply_does_not_publish_baseline(bridge_client):
    client, upstream, _ = bridge_client
    upstream.response = prediction(1000000.0)
    response = client.post("/api/v1/fluxcast/single-period/compute", json=payload())
    assert response.status_code == 503
    assert response.json()["status"] == "failed"
    assert not response.json().get("result_point")


def test_single_step_forecast_is_selected_without_changing_value():
    actual = ActualSnapshot.model_validate(complete_actual())
    assert select_target_prediction(prediction(1234.56789), actual) == 1234.56789


def test_legacy_96_point_forecast_is_rejected():
    actual = ActualSnapshot.model_validate(complete_actual())
    with pytest.raises(DispatchServiceError, match="单点"):
        select_target_prediction(prediction(count=96), actual)
