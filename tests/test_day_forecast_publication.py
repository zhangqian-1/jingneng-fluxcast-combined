"""Daily publication is persistent and must never replace the dispatch target."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api
from src.day_forecast_publication import DayForecastPublisher
from src.errors import DispatchServiceError
from src.forecast_bridge import EVENT_KEY, ForecastDispatchBridge
from src.single_period_service import SinglePeriodService
from src.single_period_store import SinglePeriodStore
from tests.test_platform_contract import platform_payload
from tests.test_single_forecast_bridge import Upstream, prediction

UTC = timezone.utc
ANCHOR = datetime(2026, 9, 21, 0, 30, tzinfo=UTC)  # Beijing 08:30
MIDNIGHT_ANCHOR = ANCHOR - timedelta(hours=8, minutes=45)  # previous Beijing 23:45


def request_at(stamp):
    return {"point_table": ["fixture"], "frames": [{"timestamp": stamp.isoformat()}]}


class DayModel:
    def __init__(self):
        self.calls = []
        self.ingestions = []
        self.damage = None

    def ingest(self, payload):
        self.ingestions.append(deepcopy(payload))
        if self.damage == "unavailable":
            raise DispatchServiceError(502, "FORECAST_UNAVAILABLE", "fixture")
        reason = "history_not_ready" if self.damage == "waiting" else "history_updated"
        return 200, {"event_key": EVENT_KEY, "result_point": [], "reason": reason}

    def request(self, payload):
        self.calls.append(deepcopy(payload))
        if self.damage == "unavailable":
            raise DispatchServiceError(502, "FORECAST_UNAVAILABLE", "fixture")
        if self.damage == "waiting":
            return 200, {"event_key": EVENT_KEY, "result_point": [], "reason": "history_not_ready"}
        stamp = datetime.fromisoformat(payload["frames"][-1]["timestamp"])
        body = {
            "event_key": EVENT_KEY,
            "result_point": [
                {
                    "varname": "totalPowerForecast",
                    "timestamp": (stamp + timedelta(minutes=15 * (n + 1))).isoformat(),
                    "value": 1500.0 + n,
                }
                for n in range(96)
            ],
        }
        if self.damage:
            self.damage(body)
        return 200, body


@pytest.fixture
def publisher(tmp_path):
    model = DayModel()
    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    return DayForecastPublisher(model, store), model, store


def prepare(service, stamp=MIDNIGHT_ANCHOR):
    publish(service, stamp, success=False)


def publish(publisher, stamp=ANCHOR, success=True, now=None):
    publisher.clock = lambda: now or stamp + timedelta(seconds=1)
    return publisher.process(
        request_at(stamp), successful=success, now=now or stamp + timedelta(seconds=1)
    )


def test_schedule_retry_restart_and_next_day(publisher):
    service, model, store = publisher
    prepare(service)
    points, status = publish(service)
    assert status == "published" and len(points) == 96
    assert {p["varname"] for p in points} == {"totalPowerForecastDayAhead"}
    assert publish(service) == (points, "replayed")
    assert len(model.calls) == 1
    assert len(model.ingestions) == 2
    assert datetime.fromisoformat(points[0]["timestamp"]) == ANCHOR - timedelta(hours=8, minutes=30)
    assert datetime.fromisoformat(points[-1]["timestamp"]) == ANCHOR + timedelta(
        hours=15, minutes=15
    )
    fresh = DayForecastPublisher(model, SinglePeriodStore(store.path))
    assert publish(fresh) == (points, "replayed")
    assert publish(fresh, ANCHOR + timedelta(minutes=15)) == ([], "already_published")
    prepare(fresh, MIDNIGHT_ANCHOR + timedelta(days=1))
    next_points, _ = publish(fresh, ANCHOR + timedelta(days=1))
    assert len(next_points) == 96 and next_points != points


@pytest.mark.parametrize("failure", ["waiting", "unavailable"])
def test_failed_model_does_not_consume_daily_publication(publisher, failure):
    service, model, _ = publisher
    model.damage = failure
    points, status = publish(service)
    assert points == [] and status == (
        "history_not_ready" if failure == "waiting" else "unavailable"
    )
    model.damage = None
    assert publish(service, ANCHOR + timedelta(minutes=15)) == ([], "day_curve_missing")
    # A rolling 24h prediction cannot replace the missing calendar-day batch.
    prepare(service, MIDNIGHT_ANCHOR + timedelta(days=1))
    assert len(publish(service, ANCHOR + timedelta(days=1))[0]) == 96


def test_pending_optimization_and_initialization_only_warm_model(publisher):
    service, model, _ = publisher
    prepare(service)
    assert publish(service, success=False) == ([], "optimization_pending")
    assert len(model.calls) == 1
    assert len(model.ingestions) == 2
    assert len(publish(service)[0]) == 96


@pytest.mark.parametrize(
    "damage",
    [
        lambda body: body["result_point"].pop(),
        lambda body: body.update(event_key="wrong"),
        lambda body: body["result_point"][0].update(value=True),
        lambda body: body["result_point"][0].update(value=float("nan")),
        lambda body: body["result_point"][0].update(value=-1.0),
        lambda body: body["result_point"][0].update(timestamp=ANCHOR.isoformat()),
        lambda body: body["result_point"][1].update(timestamp=body["result_point"][0]["timestamp"]),
        lambda body: body["result_point"][0].update(varname="wrong"),
    ],
)
def test_invalid_curve_is_not_published(publisher, damage):
    service, model, _ = publisher
    model.damage = damage
    assert publish(service, MIDNIGHT_ANCHOR) == ([], "invalid_response")
    model.damage = None
    assert publish(service) == ([], "day_curve_missing")


def test_no_previous_day_or_future_publication(publisher):
    service, _, _ = publisher
    prepare(service)
    assert publish(service, now=ANCHOR + timedelta(days=1)) == ([], "outside_publication_day")
    assert publish(service, now=ANCHOR - timedelta(minutes=15)) == ([], "future_observation")
    assert len(publish(service)[0]) == 96


def test_database_serializes_publishers(publisher):
    original, model, store = publisher
    prepare(original)
    services = [DayForecastPublisher(model, SinglePeriodStore(store.path)) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda entry: publish(entry[1], ANCHOR + timedelta(minutes=15 * entry[0])),
                enumerate(services),
            )
        )
    assert sorted(len(points) for points, _ in results) == [0, 96]


def test_api_returns_both_forecasts_without_changing_optimizer(tmp_path, monkeypatch):
    clock = [ANCHOR + timedelta(seconds=1)]
    single = Upstream(prediction())
    single.response["result_point"][0]["timestamp"] = (ANCHOR + timedelta(minutes=15)).isoformat()
    bridge = ForecastDispatchBridge(
        single, SinglePeriodService(tmp_path / "api.sqlite3", clock=lambda: clock[0])
    )
    day = DayModel()
    prepare(DayForecastPublisher(day, bridge.dispatch.store))
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    monkeypatch.setattr(api, "get_day_forecast_client", lambda: day)
    with TestClient(api.app) as client:
        payload = platform_payload(ANCHOR, style="z")
        first = client.post("/api/v1/fluxcast/compute", json=payload)
        assert first.status_code == 200, first.text
        assert first.headers["X-Fluxcast-Day-Forecast"] == "published"
        body = first.json()
        assert len(body["result_point"]) == 128 and len(body["extra_info"]) == 9
        assert len({(p["varname"], p["timestamp"]) for p in body["result_point"]}) == 128
        assert all(p["timestamp"].endswith("Z") for p in body["result_point"])
        assert (
            next(p["value"] for p in body["result_point"] if p["varname"] == "totalPowerForecast")
            == 1000.0
        )
        assert sum(
            p["value"] for p in body["result_point"] if p["varname"].endswith("_MW")
        ) == pytest.approx(1000.0)
        assert client.post("/api/v1/fluxcast/compute", json=payload).json() == body
        clock[0] += timedelta(minutes=15)
        single.response["result_point"][0]["timestamp"] = (
            clock[0] + timedelta(minutes=15, seconds=-1)
        ).isoformat()
        later = client.post(
            "/api/v1/fluxcast/compute", json=platform_payload(ANCHOR + timedelta(minutes=15))
        )
        assert later.status_code == 200, later.text
        assert len(later.json()["result_point"]) == 32
        assert len(day.calls) == 1
        assert len(day.ingestions) == 4  # warmup + first + retry + next slot
        assert later.headers["X-Fluxcast-Day-Forecast"] == "already_published"


def test_valid_day_batch_survives_rolling_model_failure(publisher):
    service, model, _ = publisher
    prepare(service)
    model.damage = "unavailable"
    assert len(publish(service)[0]) == 96


def test_different_rolling_curves_do_not_overwrite_midnight_forecast(publisher):
    service, model, store = publisher
    prepare(service)
    model.damage = lambda body: body["result_point"][0].update(value=9999.0)
    points, status = publish(service)
    assert status == "published" and points[0]["value"] == 1500.0
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM day_forecast_curve").fetchone()[0] == 1


def test_first_success_can_publish_before_0830(publisher):
    service, _, _ = publisher
    prepare(service)
    midnight = MIDNIGHT_ANCHOR + timedelta(minutes=15)
    points, state = publish(service, midnight)
    assert state == "published" and len(points) == 96
    assert publish(service, ANCHOR) == ([], "already_published")


def test_joint_api_missing_calendar_curve_keeps_optimization(tmp_path, monkeypatch):
    single = Upstream(prediction())
    stamp = ANCHOR
    single.response["result_point"][0]["timestamp"] = (stamp + timedelta(minutes=15)).isoformat()
    bridge = ForecastDispatchBridge(
        single,
        SinglePeriodService(tmp_path / "api.sqlite3", clock=lambda: stamp + timedelta(seconds=1)),
    )
    day = DayModel()
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    monkeypatch.setattr(api, "get_day_forecast_client", lambda: day)
    with TestClient(api.app) as client:
        response = client.post("/api/v1/fluxcast/compute", json=platform_payload(stamp))
        assert response.status_code == 200, response.text
        assert len(response.json()["result_point"]) == 31
        assert response.headers["X-Fluxcast-Day-Forecast"] == "day_curve_missing"


def test_initialization_proxy_feeds_both_models_without_publishing(tmp_path, monkeypatch):
    single = Upstream(prediction())
    bridge = ForecastDispatchBridge(single, SinglePeriodService(tmp_path / "api.sqlite3"))
    day = DayModel()
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    monkeypatch.setattr(api, "get_day_forecast_client", lambda: day)
    with TestClient(api.app) as client:
        request = request_at(MIDNIGHT_ANCHOR)
        response = client.post("/api/v1/fluxcast/forecast/compute", json=request)
        assert response.status_code == 200 and response.json() == single.response
        assert single.calls == day.calls == day.ingestions == [request]
        with bridge.dispatch.store.connection() as db:
            assert db.execute("SELECT count(*) FROM day_forecast_curve").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM day_forecast_publication").fetchone()[0] == 0


def test_slow_day_model_cannot_publish_late_dispatch(tmp_path, monkeypatch):
    clock = [ANCHOR + timedelta(seconds=1)]
    bridge = ForecastDispatchBridge(
        Upstream(prediction()),
        SinglePeriodService(tmp_path / "api.sqlite3", clock=lambda: clock[0]),
    )
    model = DayModel()
    request = model.ingest

    def slow(payload):
        clock[0] += timedelta(minutes=15)
        return request(payload)

    model.ingest = slow
    monkeypatch.setattr(api, "get_forecast_bridge", lambda: bridge)
    monkeypatch.setattr(api, "get_day_forecast_client", lambda: model)
    with TestClient(api.app) as client:
        response = client.post("/api/v1/fluxcast/compute", json=platform_payload(ANCHOR))
        assert response.status_code == 409, response.text
        assert response.json()["result_point"] == []
