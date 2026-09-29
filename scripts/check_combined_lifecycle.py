"""Recreate and fault-test only an explicitly isolated verification Compose project."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = """
import hashlib,json,sqlite3
from pathlib import Path
result = {}
for root in (Path('/opt/forecast-single/runtime'), Path('/opt/forecast-day/runtime')):
    for p in root.rglob('*'):
        if p.is_file(): result[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
for p in Path('/app/runtime').rglob('*.sqlite3'):
    with sqlite3.connect(p) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        result[str(p)] = db.execute('SELECT snapshot_id,body FROM rolling_result '
                                   'ORDER BY snapshot_id').fetchall()
        for table, ordering in (('price_overrides','version'),('snapshot_prices','snapshot_id'),
                                ('day_forecast_curve','day'),('day_forecast_publication','day'),
                                ('day_forecast_provenance','day'),('measured_power_result','target')):
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                (table,)).fetchone()
            if exists:
                rows = db.execute('SELECT * FROM '+table+' ORDER BY '+ordering).fetchall()
                result[str(p)+'/'+table] = rows
print(json.dumps(result))
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project.startswith("fluxcast-single-verify"):
        raise ValueError("Fault injection is restricted to isolated verification projects")
    container = args.project + "-dispatch-1"

    def inspect():
        return json.loads(
            subprocess.check_output(["docker", "inspect", container], text=True, encoding="utf-8")
        )[0]

    initial = inspect()
    assert initial["Config"]["Labels"]["com.docker.compose.project"] == args.project
    assert initial["HostConfig"]["RestartPolicy"]["Name"] == "no"
    env = {**os.environ, "DISPATCH_PORT": str(args.port)}
    compose = [
        "docker",
        "compose",
        "-p",
        args.project,
        "--env-file",
        "deploy/forecast-dispatch/.env.example",
        "-f",
        "deploy/forecast-dispatch/compose.yaml",
        "-f",
        "deploy/forecast-dispatch/compose.verify.yaml",
    ]

    def snapshot():
        return json.loads(
            subprocess.check_output(
                ["docker", "exec", container, "/app/.venv/bin/python", "-c", SNAPSHOT],
                text=True,
                encoding="utf-8",
            )
        )

    before = snapshot()
    assert any(v for k, v in before.items() if k.endswith("/platform.sqlite3"))
    assert any(k.endswith(".csv") and "forecast-single" in k for k in before)
    assert any(k.endswith(".csv") and "forecast-day" in k for k in before)
    subprocess.run(
        compose
        + [
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "360",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    assert inspect()["Id"] != initial["Id"]
    assert snapshot() == before, "Prediction history or archived optimization changed on recreation"
    print(
        "Container recreation preserves both prediction histories and optimization results",
        flush=True,
    )
    kill = """
import os,signal
from pathlib import Path
for p in Path('/proc').iterdir():
    if p.name.isdigit():
        try: args=(p/'cmdline').read_bytes().split(b'\\0')
        except (FileNotFoundError,PermissionError): continue
        if args[:2] == [b'/usr/local/bin/python', b'app/api.py']:
            os.kill(int(p.name), signal.SIGKILL)
            break
else: raise RuntimeError('Single-step process not found')
"""
    subprocess.run(["docker", "exec", container, "/app/.venv/bin/python", "-c", kill], check=True)
    deadline = time.monotonic() + 40
    while inspect()["State"]["Running"] and time.monotonic() < deadline:
        time.sleep(1)
    stopped = inspect()["State"]
    assert not stopped["Running"] and stopped["ExitCode"] != 0, stopped
    subprocess.run(
        compose + ["up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "360"],
        cwd=ROOT,
        env=env,
        check=True,
    )
    assert snapshot() == before
    report = {
        "passed": True,
        "image_id": inspect()["Image"],
        "project": args.project,
        "recreation_preserves_state": True,
        "child_failure_stops_container": True,
        "restart_preserves_state": True,
    }
    args.output.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
