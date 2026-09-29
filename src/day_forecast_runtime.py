"""Add internal history-only ingestion without editing the vendor predictor files."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HISTORY_PATH = "/api/v1/fluxcast/history"
LOG = logging.getLogger(__name__)


def configure(vendor_root, history_cache=None, latest_json=None):
    root = Path(vendor_root).resolve()
    sys.path.insert(0, str(root / "app"))
    spec = importlib.util.spec_from_file_location("vendor_day_http", root / "app/api.py")
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    from history_cache import HistoryNotReadyError

    from platform_adapter import to_model_payload

    class HistoryHandler(vendor.ForecastHandler):
        def do_POST(self):
            if urlparse(self.path).path != HISTORY_PATH:
                return super().do_POST()
            try:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise vendor.InputValidationError("Invalid Content-Length") from exc
                if length <= 0:
                    raise vendor.InputValidationError("Empty request body")
                if length > vendor.MAX_REQUEST_BYTES:
                    self.send_json(413, vendor.empty_result("request_too_large", "Body too large"))
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise vendor.InputValidationError("Invalid UTF-8 JSON") from exc
                with self.inference_lock:
                    adapted = to_model_payload(payload)
                    parsed = self.predictor.input_adapter.parse_json(adapted)
                    try:
                        _, status = self.predictor.history_cache.merge(parsed)
                        reason = "history_updated"
                    except HistoryNotReadyError as exc:
                        status = exc.status
                        reason = (
                            "weather_history_not_ready"
                            if status.get("waitingForWeatherHistory")
                            else "history_not_ready"
                        )
                self.send_json(
                    200,
                    vendor.empty_result(
                        reason,
                        "History stored; no model inference performed",
                        continuous_points=status["continuousPoints"],
                        required_points=status["requiredPoints"],
                        missing_weather_points=status.get("missingWeatherPoints", []),
                    ),
                )
            except vendor.InputValidationError as exc:
                self.send_json(400, vendor.empty_result("invalid_request", str(exc)))
            except Exception:
                LOG.exception("day_history_ingestion_failed")
                self.send_json(500, vendor.empty_result("history_failed", "See service logs"))

    HistoryHandler.predictor = vendor.PowerPredictor(
        vendor.DEFAULT_MODEL_PATH,
        device="cpu",
        history_cache_path=history_cache or vendor.DEFAULT_HISTORY_CACHE,
    )
    HistoryHandler.latest_json = Path(latest_json or vendor.DEFAULT_LATEST_JSON)
    HistoryHandler.platform_service = vendor.PlatformForecastService(HistoryHandler.predictor)
    if (
        HistoryHandler.predictor.history_cache.cache_path.resolve()
        == HistoryHandler.latest_json.resolve()
    ):
        raise ValueError("History cache and latest response must use different paths")
    return HistoryHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor-root", type=Path, default=Path("/opt/forecast-day"))
    parser.add_argument("--history-cache", type=Path)
    parser.add_argument("--latest-json", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    handler = configure(args.vendor_root, args.history_cache, args.latest_json)
    ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
