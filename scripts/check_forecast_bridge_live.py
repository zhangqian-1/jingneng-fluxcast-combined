"""Replay archived measurements through the original forecasting container.

Writes only our isolated test output/cache. Never edits the vendor delivery.
Historical replay uses an explicit test clock; production has no clock override.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import api  # noqa: E402
from src.dispatch_engine import GAS_POINTS, dispatch_config  # noqa: E402
from src.forecast_bridge import ForecastClient, ForecastDispatchBridge  # noqa: E402
from src.platform_config import RENEWABLE_FARM_IDS, STATION_CODES  # noqa: E402
from src.single_period_service import SinglePeriodService  # noqa: E402


class CombinedForecastClient(ForecastClient):
    """Use the existing initialization proxy; the internal predictor stays private."""

    def request(self, body=None):
        path = "/api/v1/fluxcast/forecast/" + ("latest" if body is None else "compute")
        request = Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body, allow_nan=False).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)


class InternalDayClient:
    """Verification-only access to the private model, without publishing a port."""

    def __init__(self, container):
        self.container = container

    def request(self, body=None):
        code = """import json,sys
from urllib.request import Request,urlopen
from urllib.error import HTTPError
body=json.load(sys.stdin)
url='http://127.0.0.1:8002/api/v1/fluxcast/compute'+('/latest' if body is None else '')
request=Request(url, data=None if body is None else json.dumps(body).encode(),
                headers={'Content-Type':'application/json'})
try: response=urlopen(request,timeout=120)
except HTTPError as error: response=error
with response: print(json.dumps([response.status,json.load(response)]))
"""
        return json.loads(
            subprocess.check_output(
                ["docker", "exec", "-i", self.container, "/app/.venv/bin/python", "-c", code],
                input=json.dumps(body),
                text=True,
                encoding="utf-8",
                timeout=150,
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, required=True, help="New isolated verification directory"
    )
    parser.add_argument("--forecast-url", default="http://127.0.0.1:18770")
    parser.add_argument(
        "--dispatch-container", help="Fresh container of the current dispatch image"
    )
    parser.add_argument(
        "--day-forecast-url", help="Only needed for legacy separate-container checks"
    )
    parser.add_argument(
        "--combined", action="store_true", help="Single container; forecast-url is dispatch"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["WORK_LOG_PATH"] = str(output / "work.jsonl")
    original = ROOT / "output/forecast-single-step/vendor/original-package"
    template = json.loads((original / "examples/platform_input_example.json").read_text("utf-8"))
    points = template["point_table"]
    columns = []
    cfg = dispatch_config()
    for code, filename, _ in GAS_POINTS:
        needed = [p for p in points if p.startswith(code + "_")]
        frame = pd.read_csv(cfg.data_dir / filename, usecols=["ts", *needed])
        frame.index = pd.to_datetime(frame.pop("ts")).dt.tz_localize("Asia/Shanghai")
        columns.append(frame)
    history = pd.concat(columns, axis=1).sort_index()
    # Earlier real weather is needed for the vendor's causal fill during October gaps.
    day = pd.Timestamp("2025-10-06", tz="Asia/Shanghai")
    # October 19 has an unavailable first thermal observation; October 30
    # supplies a valid starting observation for every thermal channel.
    replay_days = 25
    last = day + pd.Timedelta(days=replay_days) - pd.Timedelta(minutes=15)
    clock = last.tz_convert("UTC").to_pydatetime() + timedelta(seconds=1)
    service = SinglePeriodService(output / "single.sqlite3", clock=lambda: clock)
    client_type = CombinedForecastClient if args.combined else ForecastClient
    bridge = ForecastDispatchBridge(client_type(args.forecast_url, timeout=120), service)
    api.get_forecast_bridge = lambda: bridge
    reports = []
    day_reports = []
    day_client = (
        InternalDayClient(args.dispatch_container)
        if args.combined
        else ForecastClient(args.day_forecast_url, timeout=120)
    )
    # Local harness checks the optimizer; the actual container harness below
    # exercises the enabled unified API and its persisted calendar-day curves.
    api.get_day_forecast_client = lambda: None
    with TestClient(api.app) as client:
        for offset in range(replay_days):
            start = day + pd.Timedelta(days=offset)
            axis = pd.date_range(start, periods=96, freq="15min")
            rows = history.loc[axis, points].reset_index(drop=True)
            # Preserve actual nulls. Vendor alone implements its own missing-data policy.
            frames = json.loads(rows.to_json(orient="records"))
            for stamp, frame in zip(axis, frames, strict=True):
                frame["timestamp"] = stamp.tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S")
            body = {"point_table": points, "frames": frames}
            response = client.post("/api/v1/fluxcast/forecast/compute", json=body)
            result = response.json()
            print(
                offset + 1,
                response.status_code,
                result.get("reason"),
                len(result.get("result_point", [])),
                flush=True,
            )
            assert response.status_code == 200, result
            if offset < 2:
                assert result.get("reason") == "history_not_ready" and result["result_point"] == []
            reports.append(
                {
                    "day": str(start),
                    "http_status": response.status_code,
                    "reason": result.get("reason"),
                    "points": len(result.get("result_point", [])),
                }
            )
            # Each model receives the same measured history into its own cache.
            # At the third batch, the single-step model is ready but the day model is not.
            if offset == 2:
                day_status, day_latest = day_client.request()
                assert day_status == 404 and day_latest["reason"] == "no_forecast"
                assert len(result["result_point"]) == 1
            day_status, day_result = day_client.request(body)
            assert day_status == 200, day_result
            day_points = day_result["result_point"]
            if offset < 6:
                assert day_result.get("reason") == "history_not_ready" and day_points == []
            else:
                assert len(day_points) == 96, day_result
                expected = axis[-1].tz_convert("UTC") + pd.Timedelta(minutes=15)
                for n, point in enumerate(day_points):
                    assert point["varname"] == "totalPowerForecast"
                    assert pd.Timestamp(
                        point["timestamp"], tz="UTC"
                    ) == expected + n * pd.Timedelta(minutes=15)
                    assert type(point["value"]) is float and math.isfinite(point["value"])
            day_reports.append(
                {"day": str(start), "points": len(day_points), "reason": day_result.get("reason")}
            )
            print("day-ahead", offset + 1, len(day_points), flush=True)
        assert len(result["result_point"]) == 1, result
        (output / "vendor-forecast.json").write_text(json.dumps(result, indent=2), "utf-8")
        (output / "vendor-day-forecast.json").write_text(json.dumps(day_result, indent=2), "utf-8")
        (output / "vendor-request.json").write_text(json.dumps(body, indent=2), "utf-8")
        # Feasibility scenario: synthetic stopped fleet. Not a claim about plant telemetry.
        actual = {
            "snapshot_id": "vendor-live-replay-20251030",
            "timestamp": last.tz_convert("UTC").isoformat(),
            "thermal_mw": dict.fromkeys(STATION_CODES, 0.0),
            "renewable_mw": dict.fromkeys(map(str, RENEWABLE_FARM_IDS), 0.0),
            "thermal_state": {
                code: {
                    "running": False,
                    "state_since": "2025-10-01T00:00:00Z",
                    "starts_today": 0,
                    "stops_today": 0,
                }
                for code in STATION_CODES
            },
        }
        request = {
            "actual": actual,
            "forecast_request": body,
            "renewable_forecast": {
                "snapshot_id": actual["snapshot_id"],
                "forecast_id": "synthetic-zero-renewable",
                "issued_at": actual["timestamp"],
                "frames": [
                    {
                        "timestamp": (clock + timedelta(minutes=15, seconds=-1)).isoformat(),
                        "power_mw": dict.fromkeys(map(str, RENEWABLE_FARM_IDS), 0.0),
                    }
                ],
            },
        }
        response = client.post("/api/v1/fluxcast/single-period/compute", json=request)
        combined = response.json()
        assert response.status_code == 200, combined
        assert combined["horizon_steps"] == 1
        assert combined["selected_demand_mw"] == result["result_point"][0]["value"]
        balance = abs(
            sum(p["value"] for p in combined["result_point"]) - combined["selected_demand_mw"]
        )
        assert balance < 1e-5, balance
        (output / "combined-request.json").write_text(json.dumps(request, indent=2), "utf-8")
        (output / "combined-result.json").write_text(json.dumps(combined, indent=2), "utf-8")
        reports.append(
            {
                "combined_http_status": response.status_code,
                "balance_error_mw": balance,
                "selected_demand_mw": combined["selected_demand_mw"],
                "actual_and_renewable_are_synthetic": True,
            }
        )
    # The platform keeps exactly its agreed three top-level fields. Thermal
    # history is real; the dated renewable long table is explicitly a test scenario.
    target = last + pd.Timedelta(minutes=15)
    forecast_day = target.normalize()
    platform_request = {
        "point_table": [point.replace(".", "_") for point in body["point_table"]],
        "frames": [
            {key.replace(".", "_"): value for key, value in frame.items()}
            for frame in body["frames"]
        ],
        "renewable_data": [
            {
                "farmId": farm,
                "predictedTime": (forecast_day + (n + 1) * pd.Timedelta(minutes=15)).strftime(
                    "%Y%m%d%H%M"
                ),
                "predictedPower": 0.0,
                "timeSeries": 1,
                "batch": (forecast_day - pd.Timedelta(days=1) + pd.Timedelta(hours=8)).strftime(
                    "%Y%m%d%H%M"
                ),
            }
            for farm in RENEWABLE_FARM_IDS
            for n in range(96)
        ],
    }
    (output / "platform-request.json").write_text(
        json.dumps(platform_request, ensure_ascii=False, indent=2), "utf-8"
    )
    verification = {"passed": False, "history_replay": reports, "day_history_replay": day_reports}
    if args.dispatch_container:
        # The isolated harness sets a historical test clock without changing production code.
        harness = """import hashlib, json, os, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from src.forecast_bridge import ForecastClient, ForecastDispatchBridge, SingleComputePayload
from src.single_period_service import SinglePeriodService
import sys, threading, time, socket
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uvicorn
import api
envelope = json.load(sys.stdin)
body = envelope['detailed']
stamp = datetime.fromisoformat(body['actual']['timestamp']) + timedelta(seconds=1)
state_root = Path(os.environ['SINGLE_PERIOD_DB_PATH']).parent
state_root.mkdir(parents=True, exist_ok=True)
folder = Path(tempfile.mkdtemp(prefix='verification-', dir=state_root))
os.environ['WORK_LOG_PATH'] = str(folder / 'work.jsonl')
bridge = ForecastDispatchBridge(ForecastClient(os.environ['FORECAST_BASE_URL'], timeout=120),
    SinglePeriodService(folder / 'verification.sqlite3', clock=lambda: stamp))
payload = SingleComputePayload.model_validate(body)
result = bridge.compute(payload)
assert result['status'] == 'completed' and result['horizon_steps'] == 1
assert len(result['result_point']) == 27
assert bridge.compute(payload) == result
# Exercise the real public HTTP route in a separate harness process, with its
# own database/test clock. The production server's clock is never changed.
api.get_forecast_bridge = lambda: ForecastDispatchBridge(
    ForecastClient(os.environ['FORECAST_BASE_URL'], timeout=120),
    SinglePeriodService(folder / 'platform.sqlite3', clock=lambda: stamp))
from src.day_forecast_publication import DayForecastPublisher
import sqlite3
platform_store = api.get_forecast_bridge().dispatch.store
DayForecastPublisher(api.get_day_forecast_client(), platform_store)
# Leave the candidate table empty to exercise automatic recovery through HTTP.
with sqlite3.connect(os.environ['SINGLE_PERIOD_DB_PATH']) as source:
    reference_curves = dict(source.execute('SELECT day, body FROM day_forecast_curve').fetchall())
recovery = api.get_day_forecast_recovery()
original_recover = recovery.recover
recovery_calls = []
def checked_recover(day):
    live = Path('/opt/forecast-day/runtime')
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in live.rglob('*') if p.is_file()}
    answer = original_recover(day)
    after = {str(p):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in live.rglob('*') if p.is_file()}
    assert before == after, 'Recovery modified online cache/latest'
    assert len(answer['result_point']) == 96, answer
    reference = json.loads(reference_curves[day])
    assert [p['value'] for p in answer['result_point']] == [p['value'] for p in reference]
    recovery_calls.append(day)
    return answer
recovery.recover = checked_recover
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
port = sock.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(api.app, log_level='error', lifespan='off'))
thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
thread.start()
for _ in range(200):
    if server.started:
        break
    time.sleep(0.025)
assert server.started
platform_request = envelope['platform']
encoded = json.dumps(platform_request).encode()
try:
    def send():
        request = Request('http://127.0.0.1:' + str(port) + '/api/v1/fluxcast/compute',
            data=encoded, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=120) as response:
                assert response.status == 200
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(exc.read().decode()) from exc
    platform = send()
    assert send() == platform
    assert len(recovery_calls) == 1, recovery_calls
finally:
    server.should_exit = True
    thread.join(timeout=5)
assert set(platform) == {'event_key', 'result_point', 'extra_info'}
assert platform['event_key'] == 'JNH.Fluxcast.Compute'
identities = {(p['varname'], p['timestamp']) for p in platform['result_point']}
assert len(identities) == len(platform['result_point'])
assert all(type(p['value']) is float for p in platform['result_point'])
expected = (stamp + timedelta(minutes=15, seconds=-1)).strftime('%Y-%m-%d %H:%M:%S')
daily = [p for p in platform['result_point'] if p['varname']=='totalPowerForecastDayAhead']
measured_names = {'totalPowerActual', 'totalPowerDeviation'}
single = [p for p in platform['result_point']
          if p['varname'] not in measured_names | {'totalPowerForecastDayAhead'}]
assert len(daily)==96 and len(single)==30
assert {p['timestamp'] for p in single} == {expected}
from zoneinfo import ZoneInfo
local_day = stamp.astimezone(ZoneInfo('Asia/Shanghai')).replace(
    hour=0,minute=0,second=0,microsecond=0)
for n,point in enumerate(daily):
    parsed = datetime.fromisoformat(point['timestamp']).replace(tzinfo=ZoneInfo('UTC'))
    assert parsed == local_day+timedelta(minutes=15*n)
actual_strings = {'dataStatus', 'missingPoints', 'reason', 'deviationBasis'}
strings = [p for p in platform['extra_info'] if p['varname'] not in actual_strings]
assert len(strings) == 8
assert all(set(p) == {'varname', 'timestamp', 'value'} for p in strings)
assert all(type(p['value']) is str and p['timestamp'] == expected for p in strings)
states = {p['varname']: p['value'] for p in strings}
assert states['balanceStatus'] == '供需平衡'
from src.actual_power import measurement
from src.platform_adapter import PlatformComputePayload
raw_frame = PlatformComputePayload.model_validate(platform_request).forecast_request()['frames'][-1]
measured_stamp, _, missing, quality, total = measurement(raw_frame)
extras = {p['varname']:p for p in platform['extra_info']}
measured = {p['varname']:p for p in platform['result_point'] if p['varname'] in measured_names}
assert extras['dataStatus']['value'] == quality
assert extras['dataStatus']['timestamp'] == platform_request['frames'][-1]['timestamp']
if missing:
    assert measured == {} and extras['missingPoints']['value'] == ','.join(missing)
else:
    assert measured['totalPowerActual']['value'] == total
    assert measured['totalPowerActual']['timestamp'] == platform_request['frames'][-1]['timestamp']
    current_time = platform_request['frames'][-1]['timestamp']
    current_prediction = next(p['value'] for p in daily if p['timestamp'] == current_time)
    assert measured['totalPowerDeviation']['value'] == current_prediction - total
    assert measured['totalPowerDeviation']['timestamp'] == current_time
    assert extras['deviationBasis']['value'] == 'initial_curve_comparison'
    assert extras['deviationBasis']['timestamp'] == current_time
# Only the initial publication's current point gets this comparison exception.
day_client = api.get_day_forecast_client()
before_latest = day_client.request()
history_request = PlatformComputePayload.model_validate(platform_request).forecast_request()
history_status, history_body = day_client.ingest(history_request)
assert history_status == 200 and history_body['reason'] == 'history_updated'
assert day_client.request() == before_latest, 'History-only ingestion overwrote latest'
observed = datetime.fromisoformat(body['actual']['timestamp'])
platform_id = 'platform-' + observed.strftime('%Y%m%dT%H%M%SZ')
platform_bridge = api.get_forecast_bridge()
with platform_bridge.dispatch.store.connection() as db:
    platform_saved = platform_bridge.dispatch.store.result(db, platform_id)
assert all(states[code + '_planStatus'] == ('运行' if on else '停机')
           for code, on in platform_saved['thermal_running'].items())
forecast_point = next(p for p in platform['result_point']
                      if p['varname'] == 'totalPowerForecast')
assert forecast_point['value'] == result['selected_demand_mw']
power_sum = sum(p['value'] for p in platform['result_point'] if p['varname'].endswith('_MW'))
assert abs(power_sum - result['selected_demand_mw']) < 1e-5
root = Path('/app')
paths = [root/n for n in ('api.py','start.sh','pyproject.toml','uv.lock')]
for name in ('src','config','data','dashboard'):
    paths.extend(p for p in (root/name).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts)
inventory = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in paths}
print(json.dumps({'result': result, 'platform': platform, 'runtime_sha256': inventory}))
"""
        checked = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                args.dispatch_container,
                "/app/.venv/bin/python",
                "-c",
                harness,
            ],
            input=json.dumps({"detailed": request, "platform": platform_request}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=180,
        )
        (output / "container-stderr.txt").write_text(checked.stderr, "utf-8")
        if checked.returncode:
            raise RuntimeError(checked.stderr)
        container = json.loads(checked.stdout)
        result = container["result"]
        error = abs(sum(p["value"] for p in result["result_point"]) - result["selected_demand_mw"])
        assert result["selected_demand_mw"] == combined["selected_demand_mw"]
        assert error < 1e-5
        assert all(type(p["value"]) is float and p["value"] >= 0 for p in result["result_point"])
        (output / "container-result.json").write_text(json.dumps(result, indent=2), "utf-8")
        (output / "platform-result.json").write_text(
            json.dumps(container["platform"], indent=2), "utf-8"
        )
        verification.update(
            passed=True,
            platform_contract_verified=True,
            platform_route="/api/v1/fluxcast/compute",
            platform_response_points=len(container["platform"]["result_point"]),
            observations_contract_verified=True,
            initial_deviation_contract_verified=True,
            day_history_only_verified=True,
            daily_calendar_curve_verified=True,
            calendar_recovery_verified=True,
            recovery_matches_original_batch=True,
            recovery_preserves_online_cache=True,
            dual_forecast_verified=True,
            day_forecast_points=96,
            day_forecast_history_points=672,
            separate_forecast_caches_verified=True,
            forecast_horizon_points=1,
            forecast_history_points=288,
            thermal_history_is_real=True,
            thermal_state_basis="power_history_estimate",
            renewable_input_is_synthetic=True,
            runtime_sha256=container["runtime_sha256"],
            container_balance_error_mw=error,
        )
        if args.combined:
            inspection = json.loads(
                subprocess.check_output(
                    ["docker", "inspect", args.dispatch_container], text=True, encoding="utf-8"
                )
            )[0]
            project = inspection["Config"]["Labels"]["com.docker.compose.project"]
            containers = subprocess.check_output(
                ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
                text=True,
            ).split()
            assert len(containers) == 1, "Combined verification must run exactly one container"
            assert set(inspection["HostConfig"]["PortBindings"]) == {"8000/tcp"}
            verification["single_public_port_verified"] = True
            verification.update(single_container_verified=True, image_id=inspection["Image"])
    (output / "verification.json").write_text(json.dumps(verification, indent=2), "utf-8")
    print(json.dumps({"output": str(output), "container_verified": verification["passed"]}))


if __name__ == "__main__":
    main()
