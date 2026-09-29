"""Keep test audit events isolated from operational work logs."""

import pytest


@pytest.fixture(autouse=True)
def isolate_work_log(monkeypatch, tmp_path):
    monkeypatch.setenv("WORK_LOG_PATH", str(tmp_path / "work.jsonl"))
    import api

    monkeypatch.setattr(api, "get_day_forecast_client", lambda: None)
    monkeypatch.setattr(api, "get_day_forecast_recovery", lambda: None)
