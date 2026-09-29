"""Exercise the internal HTTP wrapper against real unchanged model files and CSVs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def hashes(root):
    paths = [root / "requirements.txt"]
    for directory in ("app", "models"):
        paths += [
            p for p in (root / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        ]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def verify(root, output):
    import pandas as pd

    from src.day_forecast_runtime import configure

    before = hashes(root)
    output.mkdir(parents=True, exist_ok=False)
    handler = configure(root, output / "history.csv", output / "latest.json")
    from predict import DEFAULT_MODEL_PATH, PowerPredictor

    from platform_adapter import PlatformForecastService

    spec = importlib.util.spec_from_file_location(
        "vendor_payloads", root / "tests/build_real_test_payloads.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    frames = fixtures.load_station_frames(root / "tests/real_data_raw")
    fixtures.make_payloads(frames, output / "requests", pd.Timestamp("2025-10-12 23:45:00"))
    requests = [
        json.loads(p.read_text("utf-8")) for p in sorted((output / "requests").glob("*.json"))
    ]
    predictions = []
    original_predict = handler.predictor.backend.predict

    def counted(*args, **kwargs):
        predictions.append(1)
        return original_predict(*args, **kwargs)

    handler.predictor.backend.predict = counted
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))

    def call(path, body=None):
        encoded = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/fluxcast/{path}",
            data=encoded,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = opener.open(request, timeout=180)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    try:
        for payload in requests:
            status, body = call("history", payload)
            assert status == 200, body
        assert body["reason"] == "history_updated", body
        assert not predictions
        assert call("compute/latest")[0] == 404
        status, result = call("compute", requests[-1])
        assert status == 200 and len(result["result_point"]) == 96, result
        assert len(predictions) == 1

        reference = PlatformForecastService(
            PowerPredictor(
                DEFAULT_MODEL_PATH,
                device="cpu",
                history_cache_path=output / "reference.csv",
            )
        )
        for payload in requests:
            expected = reference.compute(payload)
        assert result == expected, "History-only input changed the original 96 predictions"
        latest_before = (output / "latest.json").read_bytes()
        fixtures.make_payloads(frames, output / "next", pd.Timestamp("2025-10-13 00:00:00"))
        next_request = json.loads((output / "next/day_07.json").read_text("utf-8"))
        status, body = call("history", next_request)
        assert status == 200 and body["reason"] == "history_updated", body
        assert len(predictions) == 1
        assert (output / "latest.json").read_bytes() == latest_before
        cache = pd.read_csv(output / "history.csv")
        assert pd.Timestamp(cache["ts"].iloc[-1]) == pd.Timestamp("2025-10-13 00:00:00")
        assert call("compute/latest")[1] == result
        assert hashes(root) == before, "Original model/code files changed"
        report = {
            "passed": True,
            "real_model": handler.predictor.model_name,
            "history_requests": 8,
            "model_inferences": len(predictions),
            "forecast_points": len(result["result_point"]),
            "same_as_original_forecast": True,
            "history_continues_without_inference": True,
            "latest_not_overwritten_by_history": True,
            "original_files_unchanged": len(before),
            "http_port": server.server_port,
            "container_test": "not_run",
        }
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
        (output / "forecast.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.vendor_root.resolve(), args.output.resolve())
