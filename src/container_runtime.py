"""Supervise both original prediction processes and dispatch inside one container."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
FORECAST_URL = "http://127.0.0.1:8001"


def check_service(url, points=None):
    """A loaded model without historical data is ready to accept initialization."""
    try:
        try:
            response = urlopen(url, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            status, body = response.status, json.load(response)
        if points is None:
            return status == 200 and body.get("status") == "ok"
        if body.get("event_key") != "JNH.Fluxcast.Compute":
            return False
        if status == 404:
            return body.get("reason") == "no_forecast" and body.get("result_point") == []
        return status == 200 and len(body.get("result_point", [])) == points
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def healthy(*, predictions_only=False):
    checks = [
        check_service(FORECAST_URL + "/api/v1/fluxcast/compute/latest", 1),
        check_service("http://127.0.0.1:8002/api/v1/fluxcast/compute/latest", 96),
    ]
    if not predictions_only:
        checks.append(check_service("http://127.0.0.1:8000/health"))
    return all(checks)


def stop_processes(processes, timeout=20):
    # Signal groups, including an active solver worker, not just HTTP parents.
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    for process in processes:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for process in processes:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def main():
    if sys.argv[1:] == ["--healthcheck"]:
        return 0 if healthy() else 1
    if sys.argv[1:]:
        raise ValueError("Unsupported container runtime arguments")
    if os.environ.get("FORECAST_BASE_URL", FORECAST_URL) != FORECAST_URL:
        raise ValueError("Combined container must use the internal single-step predictor")
    if os.environ.get("DAY_FORECAST_BASE_URL", "http://127.0.0.1:8002") != "http://127.0.0.1:8002":
        raise ValueError("Combined container must use the internal day predictor")
    processes = []
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1"}
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["FORECAST_BASE_URL"] = FORECAST_URL
    env["DAY_FORECAST_BASE_URL"] = "http://127.0.0.1:8002"

    def start(name, command, cwd):
        print(f"Starting {name}", flush=True)
        process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
        processes.append(process)

    try:
        start(
            "single-step prediction (internal :8001)",
            ["/usr/local/bin/python", "app/api.py", "--host", "127.0.0.1", "--port", "8001"],
            "/opt/forecast-single",
        )
        start(
            "24-hour prediction (internal :8002)",
            ["/opt/day-venv/bin/python", str(ROOT / "src/day_forecast_runtime.py")],
            "/opt/forecast-day",
        )
        deadline = time.monotonic() + 300
        while not stopping:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("Prediction process exited during startup")
            if healthy(predictions_only=True):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Prediction startup timed out")
            time.sleep(1)
        if stopping:
            return 0
        start(
            "dispatch (:8000)",
            [
                str(ROOT / ".venv/bin/python"),
                "-m",
                "uvicorn",
                "api:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            ROOT,
        )
        failures = 0
        next_probe = time.monotonic() + 15
        while not stopping:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("A service exited; stop the container for a clean restart")
            if time.monotonic() >= next_probe:
                failures = 0 if healthy() else failures + 1
                if failures >= 3:
                    raise RuntimeError("Service health checks failed three consecutive times")
                next_probe = time.monotonic() + 15
            time.sleep(0.5)
        return 0
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    sys.exit(main())
