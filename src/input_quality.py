"""Forward-fill invalid input values with a durable, structured work log."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from src.runtime_config import output_directory

INPUT_QUALITY_POLICY = "previous_valid_first_capacity_or_error_v4"
_LOG_LOCK = Lock()


class WorkLogError(RuntimeError):
    """Do not silently continue when the required audit log cannot be written."""


def safe_original(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return repr(value)[:200]


def write_work_log(event: dict[str, Any]) -> None:
    path = Path(os.getenv("WORK_LOG_PATH", str(output_directory() / "logs/work.jsonl")))
    record = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "policy": INPUT_QUALITY_POLICY,
        **event,
    }
    line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        with _LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
    except OSError as exc:
        raise WorkLogError("工作日志无法写入，请检查日志目录权限") from exc


def normalize_series(
    raw_values: Sequence[Any],
    timestamps: Sequence[str],
    validator: Callable[[Any, int], float],
    *,
    series: str,
    previous: tuple[float, str] | None = None,
    context: dict[str, Any] | None = None,
    initial_upper_limit: float | None = None,
) -> tuple[list[float], list[dict[str, Any]]]:
    """Carry the prior effective value, tracking the last genuinely valid observation."""
    values: list[float] = []
    adjustments: list[dict[str, Any]] = []
    last_valid = previous
    for period, (raw, stamp) in enumerate(zip(raw_values, timestamps, strict=True), start=1):
        try:
            number = validator(raw, period)
        except ValueError as exc:
            use_limit = (
                period == 1
                and last_valid is None
                and initial_upper_limit is not None
                and isinstance(raw, (int, float))
                and not isinstance(raw, bool)
                and math.isfinite(raw)
                and raw > initial_upper_limit
            )
            event = {
                **(context or {}),
                "stage": "input_normalization",
                "series": series,
                "timestamp": stamp,
                "original_value": safe_original(raw),
                "reason": str(exc),
                "action": "initial_capacity_limit"
                if use_limit
                else ("carry_forward" if last_valid else "reject_no_previous"),
                "replacement_value": initial_upper_limit
                if use_limit
                else (last_valid[0] if last_valid else None),
                "source_timestamp": last_valid[1] if last_valid else None,
            }
            write_work_log(event)
            if use_limit:
                number = initial_upper_limit
                last_valid = (number, stamp)
            elif last_valid is None:
                error = type(exc)(f"{exc}；无可用的上一时刻值，无法计算")
                error.input_issue = event
                raise error from exc
            else:
                number = last_valid[0]
            adjustments.append(event)
        else:
            last_valid = (number, stamp)
        values.append(number)
    return values, adjustments
