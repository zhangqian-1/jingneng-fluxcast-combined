"""A live port alone must not mark the combined service ready."""

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from src import container_runtime as runtime


@pytest.mark.parametrize(
    "status,body,points,expected",
    [
        (200, {"status": "ok"}, None, True),
        (200, {"status": "error"}, None, False),
        (
            404,
            {"event_key": "JNH.Fluxcast.Compute", "reason": "no_forecast", "result_point": []},
            1,
            True,
        ),
        (404, {"event_key": "wrong", "reason": "no_forecast", "result_point": []}, 1, False),
        (200, {"event_key": "JNH.Fluxcast.Compute", "result_point": [{}]}, 96, False),
        (200, {"event_key": "JNH.Fluxcast.Compute", "result_point": [{}]}, 1, True),
        (500, {"event_key": "JNH.Fluxcast.Compute", "result_point": []}, 1, False),
        (200, [], 1, False),
    ],
)
def test_health_validates_model_contract(monkeypatch, status, body, points, expected):
    def fetch(*_, **__):
        stream = io.BytesIO(json.dumps(body).encode())
        if status >= 400:
            raise HTTPError("http://test", status, "test", {}, stream)
        stream.status = status
        return stream

    monkeypatch.setattr(runtime, "urlopen", fetch)
    assert runtime.check_service("http://test", points) is expected


def test_connection_failure_is_unhealthy(monkeypatch):
    def fetch(*_, **__):
        raise URLError("connection refused")

    monkeypatch.setattr(runtime, "urlopen", fetch)
    assert not runtime.check_service("http://test", 1)


def test_both_predictors_are_required_even_before_dispatch_startup(monkeypatch):
    seen = []

    def check(url, points=None):
        seen.append((url, points))
        return points != 96

    monkeypatch.setattr(runtime, "check_service", check)
    assert not runtime.healthy(predictions_only=True)
    assert [points for _, points in seen] == [1, 96]
