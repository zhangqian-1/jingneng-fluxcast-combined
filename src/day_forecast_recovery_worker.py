"""Private subprocess entry point; never write to the live model's cache/latest."""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

EVENT_KEY = "JNH.Fluxcast.Compute"


def prepare_history(source, day, points):
    """Retain causal carry columns but exclude every forecast-day observation."""
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("Expected an ISO calendar date")
    axis = pd.to_datetime(source["ts"], errors="raise")
    if (
        axis.dt.tz is not None
        or axis.hasnans
        or not axis.is_monotonic_increasing
        or axis.duplicated().any()
    ):
        raise ValueError("Invalid original model-clock history")
    cutoff = pd.Timestamp(day) - pd.Timedelta(minutes=15)
    past = source.loc[axis <= cutoff].copy()
    past["ts"] = axis.loc[past.index]
    required = pd.date_range(end=cutoff, periods=672, freq="15min")
    if len(past) < 672 or not pd.DatetimeIndex(past["ts"].tail(672)).equals(required):
        raise ValueError("Continuous real history before midnight is insufficient")
    columns = [c for c in past if c.startswith("__load::") or c.startswith("__weather::")]
    mapping = {column.rsplit("::", 1)[-1]: column for column in columns}
    if len(mapping) != len(columns) or set(mapping) != set(points):
        raise ValueError("Original point columns are incomplete")
    frames = []
    for _, row in past.tail(96).iterrows():
        stamp = row["ts"].tz_localize("Asia/Shanghai").tz_convert("UTC")
        frame = {"timestamp": stamp.strftime("%Y-%m-%d %H:%M:%S")}
        frame.update(
            {
                point: None if pd.isna(row[column]) else float(row[column])
                for point, column in mapping.items()
            }
        )
        frames.append(frame)
    payload = {"point_table": points, "frames": frames}
    json.dumps(payload, allow_nan=False)
    return past, payload


def recover(day, workspace):
    # These imports use the unchanged vendor tree and original dependency environment.
    sys.path.insert(0, "/opt/forecast-day/app")
    from predict import DEFAULT_HISTORY_CACHE, DEFAULT_MODEL_PATH, PowerPredictor

    from platform_adapter import POINT_TABLE, PlatformForecastService

    source = pd.read_csv(DEFAULT_HISTORY_CACHE)
    past, payload = prepare_history(source, day, POINT_TABLE)
    isolated = workspace / "history.csv"
    past.to_csv(isolated, index=False, encoding="utf-8-sig")
    predictor = PowerPredictor(DEFAULT_MODEL_PATH, device="cpu", history_cache_path=isolated)
    result = PlatformForecastService(predictor).compute(payload)
    if not result.get("result_point"):
        reason = result.get("reason", "unavailable")
        result["reason"] = "recovery_" + reason
    result["recovery_info"] = {
        "day": day,
        "history_end": str(past["ts"].iloc[-1]),
        "history_points": len(past),
        "future_rows_excluded": len(source) - len(past),
    }
    return result


def main():
    day, workspace = sys.argv[1:]
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = recover(day, Path(workspace))
    except (FileNotFoundError, KeyError, ValueError) as error:
        logging.warning("calendar_recovery_history_unavailable: %s", error)
        result = {
            "event_key": EVENT_KEY,
            "result_point": [],
            "reason": "recovery_history_not_ready",
        }
    except Exception:
        logging.exception("calendar_recovery_failed")
        result = {"event_key": EVENT_KEY, "result_point": [], "reason": "recovery_unavailable"}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
