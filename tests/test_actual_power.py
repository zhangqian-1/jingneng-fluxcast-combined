"""Raw measurements, UTC target identity and immutable published curve association."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src.actual_power import POINTS, ActualPower
from src.day_forecast_publication import DayForecastPublisher
from src.errors import DispatchServiceError
from src.forecast_bridge import ForecastDispatchBridge
from src.platform_config import platform_point_name
from src.single_period_models import utc_time
from src.single_period_service import SinglePeriodService
from src.single_period_store import SinglePeriodStore
from tests.test_day_forecast_publication import (
    ANCHOR,
    MIDNIGHT_ANCHOR,
    DayModel,
    prepare,
    publish,
)
from tests.test_platform_contract import platform_payload
from tests.test_single_forecast_bridge import Upstream, prediction


def frame(stamp=ANCHOR):
    return {"timestamp": stamp.isoformat(), **dict.fromkeys(POINTS, 10.0)}


def values(result, field="result_point"):
    return {p["varname"]: p["value"] for p in result[field]}


@pytest.fixture
def actual(tmp_path):
    store = SinglePeriodStore(tmp_path / "measured.sqlite3")
    publisher = DayForecastPublisher(DayModel(), store)
    prepare(publisher)
    publish(publisher)
    return ActualPower(store), publisher, store


def test_sum_matches_published_same_utc_point_and_survives_restart(actual):
    service, publisher, store = actual
    result = service.receive(frame())
    # 08:30 Beijing is point 34, not the 08:45 single-step prediction.
    assert values(result) == {"totalPowerActual": 190.0, "totalPowerDeviation": 1344.0}
    assert values(result, "extra_info") == {"dataStatus": "complete"}
    assert all(p["timestamp"] == ANCHOR.isoformat() for p in result["result_point"])
    assert ActualPower(SinglePeriodStore(store.path)).receive(frame()) == result
    with store.connection() as db:
        assert db.execute("SELECT batch_id FROM measured_power_result").fetchone()[0]
    changed = frame()
    changed[POINTS[0]] = 11.0
    with pytest.raises(DispatchServiceError, match="不得覆盖"):
        service.receive(changed)


@pytest.mark.parametrize("invalid", [None, True, "10.0", float("nan"), float("inf")])
def test_missing_raw_value_is_not_filled_from_history(actual, invalid):
    service, _, _ = actual
    payload = frame()
    payload[POINTS[0]] = invalid
    result = service.receive(payload)
    assert result["result_point"] == []
    assert values(result, "extra_info") == {"dataStatus": "incomplete", "missingPoints": POINTS[0]}


def test_all_missing_and_true_zero(actual):
    service, _, _ = actual
    missing = service.receive({"timestamp": ANCHOR.isoformat()})
    assert missing["result_point"] == []
    assert values(missing, "extra_info")["dataStatus"] == "missing"
    zero = {"timestamp": (ANCHOR + timedelta(minutes=15)).isoformat(), **dict.fromkeys(POINTS, 0.0)}
    assert values(service.receive(zero))["totalPowerActual"] == 0.0


def test_finite_negative_is_a_measurement_not_missing(actual):
    service, _, _ = actual
    payload = frame()
    payload[POINTS[0]] = -10.0
    assert values(service.receive(payload))["totalPowerActual"] == 170.0


def test_sum_overflow_is_not_returned_as_json_infinity(actual):
    service, _, _ = actual
    payload = {"timestamp": ANCHOR.isoformat(), **dict.fromkeys(POINTS, 1e308)}
    result = service.receive(payload)
    assert result["result_point"] == []
    assert values(result, "extra_info")["reason"] == "actual_out_of_range"
    json.dumps(result, allow_nan=False)


def test_unpublished_candidate_cannot_be_used_for_display_deviation(tmp_path):
    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    prepare(DayForecastPublisher(DayModel(), store))
    result = ActualPower(store).receive(frame())
    assert values(result) == {"totalPowerActual": 190.0}
    assert values(result, "extra_info")["reason"] == "no_matching_forecast"


@pytest.mark.parametrize("damage", ["late", "equal", "old_schema", "different_curve", "wrong_hash"])
def test_ineligible_curve_never_fabricates_a_deviation(actual, damage):
    service, _, store = actual
    with store.connection() as db:
        if damage == "old_schema":
            db.execute("DELETE FROM day_forecast_provenance")
        elif damage == "different_curve":
            db.execute("UPDATE day_forecast_publication SET body='[]'")
        elif damage == "wrong_hash":
            db.execute("UPDATE day_forecast_provenance SET batch_id='wrong'")
        else:
            at = ANCHOR if damage == "equal" else ANCHOR + timedelta(seconds=1)
            db.execute("UPDATE day_forecast_provenance SET available_at=?", (at.isoformat(),))
    result = service.receive(frame())
    assert values(result) == {"totalPowerActual": 190.0}


@pytest.mark.parametrize("delay_seconds", [0, 1])
def test_recovery_initial_comparison_and_future_observations(tmp_path, delay_seconds):
    from tests.test_day_forecast_recovery import Recovery

    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    recovery = Recovery()
    publisher = DayForecastPublisher(DayModel(), store, recovery=recovery)
    publish(publisher, now=ANCHOR + timedelta(seconds=delay_seconds))
    with store.connection() as db:
        provenance = db.execute("SELECT * FROM day_forecast_provenance").fetchall()
    service = ActualPower(store)
    first = service.receive(frame())
    assert values(first) == {"totalPowerActual": 190.0, "totalPowerDeviation": 1344.0}
    assert values(first, "extra_info") == {
        "dataStatus": "complete",
        "deviationBasis": "initial_curve_comparison",
    }
    assert ActualPower(SinglePeriodStore(store.path)).receive(frame()) == first
    assert "totalPowerDeviation" not in values(
        service.receive(frame(ANCHOR - timedelta(minutes=15)))
    )
    later = service.receive(frame(ANCHOR + timedelta(minutes=15)))
    assert values(later) == {"totalPowerActual": 190.0, "totalPowerDeviation": 1345.0}
    assert values(later, "extra_info") == {"dataStatus": "complete"}
    assert "totalPowerDeviation" not in values(service.receive(frame(ANCHOR + timedelta(days=1))))
    assert recovery.calls == ["2026-09-21"]
    with store.connection() as db:
        assert db.execute("SELECT * FROM day_forecast_provenance").fetchall() == provenance


@pytest.mark.parametrize(
    "damage", ["unknown_source", "other_first_target", "wrong_cutoff", "wrong_hash", "unpublished"]
)
def test_initial_exception_requires_verified_recovery_and_publication(tmp_path, damage):
    from tests.test_day_forecast_recovery import Recovery

    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    publish(DayForecastPublisher(DayModel(), store, recovery=Recovery()))
    with store.connection() as db:
        if damage == "unknown_source":
            db.execute("UPDATE day_forecast_provenance SET source='unknown'")
        elif damage == "other_first_target":
            db.execute(
                "UPDATE day_forecast_publication SET anchor=?",
                ((ANCHOR + timedelta(minutes=15)).isoformat(),),
            )
        elif damage == "wrong_cutoff":
            db.execute("UPDATE day_forecast_curve SET anchor=?", (ANCHOR.isoformat(),))
        elif damage == "wrong_hash":
            db.execute("UPDATE day_forecast_provenance SET batch_id='wrong'")
        else:
            db.execute("DELETE FROM day_forecast_publication")
    result = ActualPower(store).receive(frame())
    assert values(result) == {"totalPowerActual": 190.0}
    assert values(result, "extra_info") == {
        "dataStatus": "complete",
        "reason": "no_matching_forecast",
    }


def test_initial_recovery_does_not_impute_missing_measurement(tmp_path):
    from tests.test_day_forecast_recovery import Recovery

    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    publish(DayForecastPublisher(DayModel(), store, recovery=Recovery()))
    payload = frame()
    payload[POINTS[0]] = None
    result = ActualPower(store).receive(payload)
    assert result["result_point"] == []
    assert values(result, "extra_info") == {"dataStatus": "incomplete", "missingPoints": POINTS[0]}


def test_existing_saved_response_is_not_rewritten_after_recovery(tmp_path):
    from tests.test_day_forecast_recovery import Recovery

    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    service = ActualPower(store)
    previous = service.receive(frame())
    assert values(previous) == {"totalPowerActual": 190.0}
    publish(DayForecastPublisher(DayModel(), store, recovery=Recovery()))
    assert ActualPower(SinglePeriodStore(store.path)).receive(frame()) == previous


@pytest.mark.parametrize("style", ["space", "z", "offset"])
@pytest.mark.parametrize("stamp", [MIDNIGHT_ANCHOR + timedelta(minutes=15), ANCHOR])
def test_joint_first_recovery_returns_current_deviation_and_replays(
    tmp_path, monkeypatch, style, stamp
):
    from tests.test_day_forecast_recovery import Recovery

    clock = [stamp + timedelta(seconds=1)]
    single = Upstream(prediction())
    single.response["result_point"][0]["timestamp"] = (stamp + timedelta(minutes=15)).isoformat()
    bridge = ForecastDispatchBridge(
        single, SinglePeriodService(tmp_path / "api.sqlite3", clock=lambda: clock[0])
    )
    day, recovery = DayModel(), Recovery()
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    monkeypatch.setattr(api, "get_day_forecast_client", lambda: day)
    monkeypatch.setattr(api, "get_day_forecast_recovery", lambda: recovery)
    payload = platform_payload(stamp, style=style)
    raw = api.PlatformComputePayload.model_validate(payload).forecast_request()["frames"][-1]
    expected_actual = sum(raw[point] for point in POINTS)
    with TestClient(api.app) as client:
        first = client.post("/api/v1/fluxcast/compute", json=payload)
        assert first.status_code == 200, first.text
        assert first.headers["X-Fluxcast-Day-Forecast"] == "published"
        body = first.json()
        assert len(body["result_point"]) == 128
        daily = [p for p in body["result_point"] if p["varname"] == "totalPowerForecastDayAhead"]
        assert len(daily) == 96
        current_prediction = next(p["value"] for p in daily if utc_time(p["timestamp"]) == stamp)
        numbers, info = values(body), values(body, "extra_info")
        assert numbers["totalPowerActual"] == expected_actual
        assert numbers["totalPowerDeviation"] == current_prediction - expected_actual
        assert numbers["totalPowerForecast"] == 1000.0
        assert info["deviationBasis"] == "initial_curve_comparison"
        assert len(info) == 10
        for field in ("result_point", "extra_info"):
            for point in body[field]:
                if point["varname"] in (
                    "totalPowerActual",
                    "totalPowerDeviation",
                    "deviationBasis",
                ):
                    assert point["timestamp"] == payload["frames"][-1]["timestamp"]
        assert client.post("/api/v1/fluxcast/compute", json=payload).json() == body

        clock[0] += timedelta(minutes=15)
        single.response["result_point"][0]["timestamp"] = (
            stamp + timedelta(minutes=30)
        ).isoformat()
        later = client.post(
            "/api/v1/fluxcast/compute",
            json=platform_payload(stamp + timedelta(minutes=15), style=style),
        )
        assert later.status_code == 200, later.text
        assert later.headers["X-Fluxcast-Day-Forecast"] == "already_published"
        assert len(later.json()["result_point"]) == 32
        assert "totalPowerDeviation" in values(later.json())
        assert "deviationBasis" not in values(later.json(), "extra_info")
    assert recovery.calls == ["2026-09-21"]
    assert not day.calls and len(day.ingestions) == 3
    with bridge.dispatch.store.connection() as db:
        assert db.execute("SELECT count(*) FROM measured_power_result").fetchone()[0] == 2


def test_initial_comparison_example_matches_calculated_result(tmp_path):
    from src.platform_adapter import _output_timestamp
    from tests.test_day_forecast_recovery import Recovery

    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    publish(DayForecastPublisher(DayModel(), store, recovery=Recovery()))
    result = ActualPower(store).receive(frame())
    for field in ("result_point", "extra_info"):
        for point in result[field]:
            point["timestamp"] = _output_timestamp(point["timestamp"], "2026-09-21 00:30:00")
    result["event_key"] = "JNH.Fluxcast.Compute"
    example = (
        Path(__file__).resolve().parents[1] / "examples/observations-initial-output-fragment.json"
    )
    assert result == json.loads(example.read_text("utf-8"))


@pytest.mark.parametrize("style", ["space", "z", "offset"])
def test_joint_http_uses_last_raw_frame_not_dispatch_fills(tmp_path, monkeypatch, style):
    stamp = ANCHOR
    single = Upstream(prediction())
    single.response["result_point"][0]["timestamp"] = (stamp + timedelta(minutes=15)).isoformat()
    bridge = ForecastDispatchBridge(
        single,
        SinglePeriodService(tmp_path / "api.sqlite3", clock=lambda: stamp + timedelta(seconds=1)),
    )
    day = DayModel()
    publisher = DayForecastPublisher(day, bridge.dispatch.store)
    prepare(publisher)
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    monkeypatch.setattr(api, "get_day_forecast_client", lambda: day)
    payload = platform_payload(stamp, style=style)
    # Earlier real readings let dispatch apply its own policy. The raw last point is missing.
    point = platform_point_name(POINTS[0])
    payload["frames"][-1][point] = None
    with TestClient(api.app) as client:
        response = client.post("/api/v1/fluxcast/compute", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "totalPowerActual" not in values(body)
    assert "totalPowerDeviation" not in values(body)
    info = {p["varname"]: p for p in body["extra_info"]}
    assert info["dataStatus"]["value"] == "incomplete"
    assert info["missingPoints"]["value"] == POINTS[0]
    assert info["dataStatus"]["timestamp"] == payload["frames"][-1]["timestamp"]
    assert len(day.calls) == 1


def test_boundary_generates_one_curve_and_later_calls_only_ingest(tmp_path):
    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    model = DayModel()
    service = DayForecastPublisher(model, store)
    prepare(service)
    for i in range(96):
        stamp = MIDNIGHT_ANCHOR + timedelta(minutes=15 * i)
        publish(service, stamp, success=False)
    assert len(model.calls) == 1
    assert len(model.ingestions) == 97
    # Recreating the coordinator cannot regenerate an existing day batch.
    prepare(DayForecastPublisher(model, SinglePeriodStore(store.path)))
    assert len(model.calls) == 1
    prepare(service, MIDNIGHT_ANCHOR + timedelta(days=1))
    assert len(model.calls) == 2


def test_documented_fragment_matches_calculated_result(actual):
    from src.platform_adapter import _output_timestamp

    service, _, _ = actual
    result = service.receive(frame())
    for field in ("result_point", "extra_info"):
        for point in result[field]:
            point["timestamp"] = _output_timestamp(point["timestamp"], "2026-09-21 00:30:00")
    result["event_key"] = "JNH.Fluxcast.Compute"
    example = Path(__file__).resolve().parents[1] / "examples/observations-output-fragment.json"
    assert result == json.loads(example.read_text("utf-8"))


def test_parallel_midnight_generation_and_provenance_are_unique(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    model = DayModel()
    publishers = [DayForecastPublisher(model, SinglePeriodStore(store.path)) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(prepare, publishers))
    assert len(model.calls) == 1
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM day_forecast_curve").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM day_forecast_provenance").fetchone()[0] == 1
