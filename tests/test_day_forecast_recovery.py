"""Recovery must use a complete pre-midnight history and a disposable cache."""

import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.day_forecast_publication import DayForecastPublisher
from src.day_forecast_recovery import DayForecastRecovery
from src.day_forecast_recovery_worker import prepare_history
from src.single_period_store import SinglePeriodStore
from tests.test_day_forecast_publication import ANCHOR, MIDNIGHT_ANCHOR, DayModel, publish


def history():
    return pd.DataFrame(
        {
            "ts": pd.date_range("2026-09-14", periods=768, freq="15min"),
            "__load::station::power": range(768),
            "__weather::station::weather": [23.0] * 768,
            "__weather_before::__weather::station::weather": [22.0] * 768,
        }
    )


def test_cutoff_excludes_entire_forecast_day_and_preserves_history():
    source = history()
    original = source.copy(deep=True)
    past, request = prepare_history(source, "2026-09-21", ["power", "weather"])
    assert len(past) == 672 and len(request["frames"]) == 96
    assert past["ts"].max() == pd.Timestamp("2026-09-20 23:45")
    assert request["frames"][-1] == {
        "timestamp": "2026-09-20 15:45:00",
        "power": 671.0,
        "weather": 23.0,
    }
    pd.testing.assert_frame_equal(source, original)
    source.loc[672:, "__load::station::power"] = 1e9
    repeated, again = prepare_history(source, "2026-09-21", ["power", "weather"])
    pd.testing.assert_frame_equal(past, repeated)
    assert again == request


@pytest.mark.parametrize(
    "damage",
    [
        lambda frame: frame.iloc[1:],
        lambda frame: frame.drop(index=650),
        lambda frame: frame.drop(index=671),
        lambda frame: pd.concat([frame, frame.iloc[:1]]),
        lambda frame: frame.iloc[::-1],
    ],
)
def test_incomplete_or_disordered_history_cannot_be_reconstructed(damage):
    with pytest.raises(ValueError):
        prepare_history(damage(history()), "2026-09-21", ["power", "weather"])


def test_observed_null_is_not_fabricated_by_recovery():
    source = history()
    source.loc[671, "__weather::station::weather"] = float("nan")
    _, request = prepare_history(source, "2026-09-21", ["power", "weather"])
    assert request["frames"][-1]["weather"] is None
    json.dumps(request, allow_nan=False)


def test_timeout_removes_isolated_cache(monkeypatch):
    paths = []

    def timeout(command, **kwargs):
        workspace = Path(command[-1])
        paths.append(workspace)
        (workspace / "history.csv").write_text("fixture")
        raise subprocess.TimeoutExpired(command, 45)

    monkeypatch.setattr(subprocess, "run", timeout)
    response = DayForecastRecovery().recover("2026-09-21")
    assert response["reason"] == "recovery_unavailable"
    assert paths and all(not path.exists() for path in paths)


def test_unwritable_temporary_directory_is_not_fatal(monkeypatch):
    import tempfile

    def denied(**kwargs):
        raise PermissionError("fixture")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", denied)
    assert DayForecastRecovery().recover("2026-09-21")["reason"] == "recovery_unavailable"


@pytest.mark.parametrize("stdout", ['{"result_point": NaN}', "[]", "invalid"])
def test_bad_worker_response_does_not_escape(monkeypatch, stdout):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout, "")
    )
    assert DayForecastRecovery().recover("2026-09-21")["reason"] == "recovery_invalid_response"


class Recovery:
    def __init__(self):
        self.calls = []
        self.ready = True

    def recover(self, day):
        self.calls.append(day)
        if not self.ready:
            return {
                "event_key": "JNH.Fluxcast.Compute",
                "result_point": [],
                "reason": "recovery_history_not_ready",
            }
        return DayModel().request({"frames": [{"timestamp": MIDNIGHT_ANCHOR.isoformat()}]})[1]


def test_missed_midnight_batch_recovers_once_and_persists(tmp_path):
    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    recovery = Recovery()
    service = DayForecastPublisher(DayModel(), store, recovery=recovery)
    points, state = publish(service)
    assert len(points) == 96 and state == "published"
    assert recovery.calls == ["2026-09-21"]
    assert publish(service) == (points, "replayed")
    fresh = DayForecastPublisher(DayModel(), SinglePeriodStore(store.path), recovery=recovery)
    assert publish(fresh, ANCHOR + timedelta(minutes=15)) == ([], "already_published")
    assert recovery.calls == ["2026-09-21"]
    assert publish(fresh) == (points, "replayed")


def test_failed_recovery_leaves_opportunity_for_next_request(tmp_path):
    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    recovery = Recovery()
    recovery.ready = False
    service = DayForecastPublisher(DayModel(), store, recovery=recovery)
    assert publish(service) == ([], "recovery_history_not_ready")
    recovery.ready = True
    assert len(publish(service, ANCHOR + timedelta(minutes=15))[0]) == 96


@pytest.mark.parametrize(
    "damage",
    [
        lambda body: body["result_point"][0].update(timestamp=ANCHOR.isoformat()),
        lambda body: body["result_point"][0].update(value=-1.0),
        lambda body: body["result_point"].pop(),
    ],
)
def test_recovered_response_must_pass_calendar_validation(tmp_path, damage):
    store = SinglePeriodStore(tmp_path / "state.sqlite3")
    recovery = Recovery()
    original = recovery.recover

    def damaged(day):
        body = original(day)
        damage(body)
        return body

    recovery.recover = damaged
    service = DayForecastPublisher(DayModel(), store, recovery=recovery)
    assert publish(service) == ([], "recovery_invalid_response")
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM day_forecast_publication").fetchone()[0] == 0
    recovery.recover = original
    assert len(publish(service)[0]) == 96
