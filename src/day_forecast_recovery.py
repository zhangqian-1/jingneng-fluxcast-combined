"""Run the original day model in its own environment with a disposable cache."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from src.forecast_bridge import EVENT_KEY


class DayForecastRecovery:
    def __init__(self, python="/opt/day-venv/bin/python", timeout=45):
        self.python, self.timeout = python, timeout

    def recover(self, day):
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Expected an ISO calendar date")
        try:
            return self._run(day)
        except OSError:
            return {"event_key": EVENT_KEY, "result_point": [], "reason": "recovery_unavailable"}

    def _run(self, day):
        reason = "recovery_unavailable"
        with tempfile.TemporaryDirectory(prefix="fluxcast-day-recovery-") as workspace:
            try:
                result = subprocess.run(
                    [
                        self.python,
                        str(Path(__file__).with_name("day_forecast_recovery_worker.py")),
                        day,
                        workspace,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    check=False,
                )
                if result.returncode == 0:
                    reason = "recovery_invalid_response"
                    if len(result.stdout) > 1024 * 1024:
                        raise ValueError("Oversized recovery response")
                    body = json.loads(result.stdout)
                    if not isinstance(body, dict) or body.get("event_key") != EVENT_KEY:
                        raise ValueError("Invalid recovery response")
                    json.dumps(body, allow_nan=False)
                    return body
            except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError):
                pass
        return {"event_key": EVENT_KEY, "result_point": [], "reason": reason}
