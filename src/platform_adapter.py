"""The agreed point_table/frames/renewable_data contract over the one-step engine."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from src.errors import DispatchServiceError
from src.forecast_bridge import EVENT_KEY, SingleComputePayload
from src.input_quality import normalize_series, write_work_log
from src.platform_config import (
    RENEWABLE_FARM_IDS,
    STATION_CODES,
    STATION_MEASUREMENT_POINTS,
    load_renewable_capacities,
    platform_point_name,
)
from src.renewable_provider import LOCAL_TIMEZONE, LongTableRenewableProvider, RenewableInputError
from src.runtime_config import REPOSITORY_ROOT
from src.single_period_models import STEP, ActualSnapshot, StrictModel, nonnegative, utc_time

_POINTS = json.loads(
    (REPOSITORY_ROOT / "config/forecast_measurement_points.json").read_text("utf-8")
)["point_table"]
_ALIASES = {platform_point_name(p): p for p in _POINTS}


def _canonical(point):
    return _ALIASES.get(point, point)


class PlatformComputePayload(StrictModel):
    point_table: list[str] = Field(min_length=1, description="全场站测点，支持约定的点号转义")
    frames: list[dict[str, Any]] = Field(
        min_length=96, max_length=96, description="连续96帧历史实测，末帧为当前时刻，UTC"
    )
    renewable_data: list[dict[str, Any]] = Field(
        min_length=1, description="19个farmId的原始长表data合并数组"
    )

    @model_validator(mode="after")
    def validate_history(self):
        points = [_canonical(p) for p in self.point_table]
        if len(points) != len(set(points)):
            raise ValueError("point_table存在重复测点或原始名与转义名冲突")
        missing = sorted(set(_POINTS) - set(points))
        if missing:
            raise ValueError("point_table缺少原预测模型测点: " + ", ".join(missing))
        try:
            stamps = [utc_time(frame["timestamp"]) for frame in self.frames]
            expected = [stamps[0] + n * STEP for n in range(96)]
            stamps[-1] + 2 * STEP
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("历史时间戳无效") from exc
        if stamps != expected or any(s.minute % 15 or s.second or s.microsecond for s in stamps):
            raise ValueError("历史必须连续升序、每15分钟一帧，不得重复或错位")
        for frame in self.frames:
            canonical_keys = [_canonical(k) for k in frame if k != "timestamp"]
            if len(canonical_keys) != len(set(canonical_keys)):
                raise ValueError("同一帧的原始测点名与转义名重复")
        try:
            json.dumps(self.model_dump(), allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValueError("请求须使用标准JSON，缺测用null表示") from exc
        return self

    def forecast_request(self):
        return {
            "point_table": sorted(_POINTS),
            "frames": [
                {
                    **{_canonical(k): v for k, v in frame.items() if _canonical(k) in _POINTS},
                    "timestamp": utc_time(frame["timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
                }
                for frame in self.frames
            ],
        }


def _renewable_target(records, target):
    """Only day-one rows; interval ends in Beijing time become UTC interval starts."""
    selected = []
    for row in records:
        series = row.get("timeSeries")
        if type(series) is not int or series < 1:
            raise RenewableInputError("timeSeries必须为正整数")
        if series == 1:
            if not isinstance(row.get("predictedTime"), str):
                raise RenewableInputError("predictedTime必须是YYYYMMDDHHmm字符串")
            selected.append(row)
    if not selected:
        raise RenewableInputError("renewable_data缺少timeSeries=1预测")
    day = target.astimezone(LOCAL_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    axis = [
        (day + n * STEP).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") for n in range(96)
    ]
    # A missing day/row is not a missing numeric value. Never extend a previous
    # day's last prediction into an entirely absent target day.
    required_ends = {(day + (n + 1) * STEP).strftime("%Y%m%d%H%M") for n in range(96)}
    for farm in RENEWABLE_FARM_IDS:
        provided = {r.get("predictedTime") for r in selected if r.get("farmId") == farm}
        if not required_ends.issubset(provided):
            raise RenewableInputError(
                f"farmId={farm}的timeSeries=1未完整覆盖目标日96个时段，不沿用过期预测"
            )
    provider = LongTableRenewableProvider(
        load_renewable_capacities(REPOSITORY_ROOT / "config/renewable_capacities.json")
    )
    forecast = provider.load(selected, axis)
    index = axis.index(target.strftime("%Y-%m-%d %H:%M:%S"))
    issued = (
        datetime.strptime(forecast.forecast_batch, "%Y%m%d%H%M")
        .replace(tzinfo=LOCAL_TIMEZONE)
        .astimezone(timezone.utc)
    )
    return (
        forecast,
        issued,
        {
            str(farm): float(forecast.values_mw[i, index])
            for i, farm in enumerate(forecast.farm_ids)
        },
    )


def _actual_from_history(request, snapshot_id, day_timezone, previous=None):
    """Observed power transitions estimate state; missing renewable actuals stay unknown."""
    frames = request["frames"]
    stamps = [utc_time(f["timestamp"]) for f in frames]
    zone = ZoneInfo(day_timezone)
    today = stamps[-1].astimezone(zone).date()
    power, states = {}, {}
    for code, points in STATION_MEASUREMENT_POINTS.items():
        cleaned = []
        for point in points:
            values, _ = normalize_series(
                [f.get(point) for f in frames],
                [s.isoformat() for s in stamps],
                lambda value, _period: nonnegative(value),
                series=point,
                context={"snapshot_id": snapshot_id, "basis": "thermal_power_history"},
            )
            cleaned.append(values)
        totals = [sum(v[n] for v in cleaned) for n in range(96)]
        running = [v > 1.0 for v in totals]  # Existing station model's power threshold.
        last_change = max([0, *[n for n in range(1, 96) if running[n] != running[n - 1]]])
        since = stamps[last_change]
        transitions = [
            (stamps[n], running[n]) for n in range(1, 96) if running[n] != running[n - 1]
        ]
        starts = sum(on for stamp, on in transitions if stamp.astimezone(zone).date() == today)
        stops = sum(not on for stamp, on in transitions if stamp.astimezone(zone).date() == today)
        # At an unobserved midnight boundary, reserve a possible event instead of
        # claiming the daily count is known to be zero.
        if stamps[0].astimezone(zone).date() == today:
            starts += int(running[0])
            stops += int(not running[0])
        if previous is not None and previous.timestamp < stamps[-1]:
            old = previous.thermal_state[code]
            if since <= previous.timestamp and old.running == running[-1]:
                since = min(since, old.state_since)
            if previous.timestamp.astimezone(zone).date() == today:
                later = [(stamp, on) for stamp, on in transitions if stamp > previous.timestamp]
                starts = max(starts, old.starts_today + sum(on for _, on in later))
                stops = max(stops, old.stops_today + sum(not on for _, on in later))
        power[code] = totals[-1]
        states[code] = {
            "running": running[-1],
            "state_since": since,
            "starts_today": starts,
            "stops_today": stops,
        }
    return ActualSnapshot(
        snapshot_id=snapshot_id,
        timestamp=stamps[-1],
        thermal_mw=power,
        renewable_mw=None,
        thermal_state=states,
        state_basis="power_history_estimate",
    )


def _output_timestamp(stamp, template):
    parsed = datetime.fromisoformat(template.replace("Z", "+00:00"))
    instant = utc_time(stamp)
    separator = "T" if "T" in template else " "
    text = instant.strftime(f"%Y-%m-%d{separator}%H:%M:%S")
    fraction = re.search(r"([.,])(\d+)", template)
    if fraction:
        text += fraction[1] + f"{instant.microsecond:06d}"[: len(fraction[2])]
    if parsed.tzinfo is None:
        return text
    if template.endswith("Z"):
        return text + "Z"
    return text + ("+00:00" if ":" in template[-6:] else "+0000")


def _plan_extra_info(result, timestamp):
    """Publish planned states from the validated solve, never inferred from MW."""
    running = result.get("thermal_running")
    if (
        not isinstance(running, dict)
        or set(running) != set(STATION_CODES)
        or any(type(value) is not bool for value in running.values())
    ):
        raise DispatchServiceError(503, "PLATFORM_RESULT_INVALID", "求解结果缺少合法的七站计划状态")
    # Completed results have passed the solver's supply/demand constraint check.
    return [
        {"varname": "balanceStatus", "timestamp": timestamp, "value": "供需平衡"},
        *[
            {
                "varname": f"{code}_planStatus",
                "timestamp": timestamp,
                "value": "运行" if running[code] else "停机",
            }
            for code in STATION_CODES
        ],
    ]


def compute_platform(payload, bridge):
    # Share the existing process lock through adaptation, input selection and publication.
    with bridge.lock:
        request = payload.forecast_request()
        stamp = utc_time(request["frames"][-1]["timestamp"])
        snapshot_id = "platform-" + stamp.strftime("%Y%m%dT%H%M%SZ")
        try:
            forecast, issued, powers = _renewable_target(payload.renewable_data, stamp + STEP)
            with bridge.dispatch.store.connection() as db:
                inputs = bridge.dispatch.store.inputs(db, snapshot_id)
                previous = bridge.dispatch.store.latest_actual(db, snapshot_id, with_state=True)
            actual = _actual_from_history(
                request,
                snapshot_id,
                bridge.dispatch.day_timezone,
                ActualSnapshot.model_validate(previous) if previous else None,
            )
            # Reuse the original observation anchor when a window is retried.
            if "actuals" in inputs:
                actual = ActualSnapshot.model_validate(inputs["actuals"])
            internal = SingleComputePayload(
                actual=actual,
                forecast_request=request,
                renewable_forecast={
                    "snapshot_id": snapshot_id,
                    "forecast_id": "platform-" + forecast.payload_hash,
                    "issued_at": issued,
                    "frames": [{"timestamp": stamp + STEP, "power_mw": powers}],
                },
            )
        except (ValueError, OverflowError) as exc:
            write_work_log(
                {
                    "stage": "platform_adapter",
                    "snapshot_id": snapshot_id,
                    "action": "rejected",
                    "reason": str(exc),
                }
            )
            raise DispatchServiceError(422, "PLATFORM_INPUT_INVALID", str(exc)) from exc
        digest = hashlib.sha256(
            json.dumps(
                {
                    "forecast_request": request,
                    "renewable_data": sorted(
                        payload.renewable_data, key=lambda row: json.dumps(row, sort_keys=True)
                    ),
                },
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        with bridge.dispatch.store.connection() as db:
            bridge.dispatch.store.put(
                db,
                "platform_request",
                {
                    "snapshot_id": snapshot_id,
                    "request_sha256": digest,
                    "state_basis": "power_history_estimate",
                    "renewable_actual_basis": "not_provided",
                    "renewable_batch": forecast.forecast_batch,
                },
            )
        result = bridge.compute(internal)
        body = {"event_key": EVENT_KEY, "result_point": [], "extra_info": []}
        if result["status"] != "completed":
            if result["status"] == "failed":
                raise DispatchServiceError(
                    result["http_status"], result["error_code"], result["detail"]
                )
            body.update(status=result["status"])
            if result["status"] == "waiting_forecast":
                body["reason"] = result["forecast_status"].get("reason", "history_not_ready")
            return (409 if result["status"] in ("expired", "superseded") else 202), body
        timestamp = _output_timestamp(result["effective_at"], payload.frames[-1]["timestamp"])
        points = [
            {**p, "timestamp": timestamp, "value": float(p["value"])}
            for p in result["result_point"]
        ]
        forecast_value = result.get("selected_demand_mw")
        if (
            type(forecast_value) not in (int, float)
            or not math.isfinite(forecast_value)
            or forecast_value < 0
        ):
            raise DispatchServiceError(
                503, "PLATFORM_RESULT_INVALID", "本次优化缺少有效的原始功率预测值"
            )
        points.append(
            {
                "varname": "totalPowerForecast",
                "timestamp": timestamp,
                "value": float(forecast_value),
            }
        )
        points += [
            {"varname": name, "timestamp": timestamp, "value": float(result["step_metrics"][name])}
            for name in ("objectiveYuan", "carbonTon")
        ]
        if not all(math.isfinite(p["value"]) for p in points) or len(
            {(p["varname"], p["timestamp"]) for p in points}
        ) != len(points):
            raise DispatchServiceError(503, "PLATFORM_RESULT_INVALID", "求解结果不符合平台数值契约")
        body["result_point"] = points
        body["extra_info"] = _plan_extra_info(result, timestamp)
        return 200, body
