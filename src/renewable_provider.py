"""Realtime renewable forecast providers and strict capacity validation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from src.input_quality import normalize_series
from src.platform_config import RENEWABLE_FARM_IDS

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


class RenewableInputError(ValueError):
    """Raised when forecast data violates shape, value, time, or capacity rules."""

    error_code = "INVALID_RENEWABLE_FORECAST"


@dataclass(frozen=True)
class RenewableForecast:
    farm_ids: tuple[int, ...]
    values_mw: np.ndarray
    normalized_utc: tuple[str, ...]
    payload_hash: str
    forecast_batch: str | None = None
    adjustments: tuple[dict[str, Any], ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "farm_ids": list(self.farm_ids),
            "values_mw": self.values_mw.astype(float).tolist(),
            "normalized_utc": list(self.normalized_utc),
            "payload_hash": self.payload_hash,
            "forecast_batch": self.forecast_batch,
            "adjustments": list(self.adjustments),
        }


def renewable_fields() -> tuple[str, ...]:
    return tuple(f"farm_{farm_id}_predictedPower" for farm_id in RENEWABLE_FARM_IDS)


def _normalized_utc(raw: Any, period: int) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise RenewableInputError(f"新能源第{period}点timestamp缺失或无效")
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RenewableInputError(f"新能源第{period}点timestamp格式无效") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _power(value: Any, farm_id: int, period: int, capacity: float) -> float:
    if isinstance(value, bool):
        raise RenewableInputError(f"farmId={farm_id}第{period}点预测值必须是非负有限浮点数")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RenewableInputError(
            f"farmId={farm_id}第{period}点预测值必须是非负有限浮点数"
        ) from exc
    if not math.isfinite(number) or number < 0:
        raise RenewableInputError(f"farmId={farm_id}第{period}点预测值必须是非负有限浮点数")
    if number > capacity + 1e-6:
        raise RenewableInputError(
            f"farmId={farm_id}第{period}点预测值{number:.3f} MW超过装机容量{capacity:.3f} MW"
        )
    return number


def _hash_forecast(axis: Sequence[str], values: np.ndarray) -> str:
    encoded = json.dumps(
        {
            "normalized_utc": list(axis),
            "farm_ids": RENEWABLE_FARM_IDS,
            "values_mw": values.tolist(),
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class InlineRenewableProvider:
    """Validate forecast fields supplied in frame-compatible upstream output."""

    def __init__(self, capacities: Mapping[int, float]) -> None:
        if set(capacities) != set(RENEWABLE_FARM_IDS):
            raise RenewableInputError("新能源装机容量配置未完整覆盖19个farmId")
        self.capacities = {farm_id: float(capacities[farm_id]) for farm_id in RENEWABLE_FARM_IDS}

    def load(
        self,
        frames: Sequence[Mapping[str, Any]],
        normalized_timestamps: Sequence[str],
        *,
        previous: Mapping[int, tuple[float, str]] | None = None,
        context: dict[str, Any] | None = None,
    ) -> RenewableForecast:
        if len(frames) != 96 or len(normalized_timestamps) != 96:
            raise RenewableInputError("新能源预测必须恰好包含96点")
        expected_axis = tuple(normalized_timestamps)
        values = np.zeros((len(RENEWABLE_FARM_IDS), 96), dtype=float)
        checked_frames = []
        for period, raw_frame in enumerate(frames, start=1):
            frame = raw_frame
            if not isinstance(frame, Mapping):
                raise RenewableInputError(f"新能源第{period}点必须是JSON对象")
            actual_timestamp = _normalized_utc(frame.get("timestamp"), period)
            if actual_timestamp != expected_axis[period - 1]:
                raise RenewableInputError(f"新能源第{period}点时间轴与燃机场站批次不一致")
            checked_frames.append(frame)
        adjustments = []
        for farm_index, farm_id in enumerate(RENEWABLE_FARM_IDS):
            field = f"farm_{farm_id}_predictedPower"

            def validate(value, period, field=field, farm_id=farm_id):
                if value is None:
                    raise RenewableInputError(f"新能源第{period}点缺少字段或空值{field}")
                return _power(value, farm_id, period, self.capacities[farm_id])

            series, changes = normalize_series(
                [frame.get(field) for frame in checked_frames],
                [f"{stamp}+00:00" for stamp in expected_axis],
                validate,
                series=field,
                previous=(previous or {}).get(farm_id),
                context=context,
                initial_upper_limit=self.capacities[farm_id],
            )
            values[farm_index] = series
            adjustments.extend(changes)

        return RenewableForecast(
            farm_ids=RENEWABLE_FARM_IDS,
            values_mw=values,
            normalized_utc=expected_axis,
            payload_hash=hashlib.sha256(
                (
                    _hash_forecast(expected_axis, values) + json.dumps(adjustments, sort_keys=True)
                ).encode()
            ).hexdigest(),
            adjustments=tuple(adjustments),
        )


def forecast_records(payload: Any) -> list[dict[str, Any]]:
    """Read native code/msg/data responses and the earlier archived envelope."""
    if isinstance(payload, Mapping) and "short_term_forecast" in payload:
        payload = payload["short_term_forecast"].get("response")
    if not isinstance(payload, Mapping) or payload.get("code", 200) != 200:
        raise RenewableInputError("新能源文件不是成功的预测响应")
    records = payload.get("data")
    if not isinstance(records, list) or not records:
        raise RenewableInputError("新能源预测响应缺少非空data列表")
    return records


def read_forecast_files(directory: str | Path) -> list[dict[str, Any]]:
    """Read all 19 files; never fall back to files in an output directory."""
    directory = Path(directory)
    expected = {f"farm_{farm_id}.json" for farm_id in RENEWABLE_FARM_IDS}
    if {path.name for path in directory.glob("farm_*.json")} != expected:
        raise RenewableInputError("新能源目录必须完整包含约定的19个farm文件")
    records = []
    for farm_id in RENEWABLE_FARM_IDS:
        try:
            payload = json.loads((directory / f"farm_{farm_id}.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RenewableInputError(f"farmId={farm_id}预测文件无法读取") from exc
        rows = forecast_records(payload)
        if any(not isinstance(row, Mapping) or row.get("farmId") != farm_id for row in rows):
            raise RenewableInputError(f"farmId={farm_id}与预测文件内容不一致")
        records.extend(rows)
    return records


class LongTableRenewableProvider:
    """Convert upstream interval-end records once, selecting the requested day by time."""

    def __init__(self, capacities: Mapping[int, float]) -> None:
        self.validator = InlineRenewableProvider(capacities)

    def load(
        self, records: Sequence[Mapping[str, Any]], normalized_timestamps: Sequence[str]
    ) -> RenewableForecast:
        axis = tuple(normalized_timestamps)
        if len(axis) != 96 or len(set(axis)) != 96:
            raise RenewableInputError("新能源目标时间轴必须包含96个不同的时段")
        frames = {stamp: {"timestamp": f"{stamp}+00:00"} for stamp in axis}
        batches: set[str] = set()
        seen: set[tuple[int, str]] = set()
        prior_stamp = (
            datetime.strptime(axis[0], "%Y-%m-%d %H:%M:%S") - timedelta(minutes=15)
        ).strftime("%Y-%m-%d %H:%M:%S")
        previous = {}
        for row in records:
            if not isinstance(row, Mapping):
                raise RenewableInputError("renewable_data每条记录必须是JSON对象")
            farm_id = row.get("farmId")
            if type(farm_id) is not int or farm_id not in RENEWABLE_FARM_IDS:
                raise RenewableInputError("新能源记录包含无效或未知farmId")
            raw_time = row.get("predictedTime")
            batch = row.get("batch")
            for name, value in (("predictedTime", raw_time), ("batch", batch)):
                if not isinstance(value, str) or len(value) != 12 or not value.isdigit():
                    raise RenewableInputError(f"新能源{name}必须是YYYYMMDDHHmm字符串")
            try:
                end = datetime.strptime(raw_time, "%Y%m%d%H%M").replace(tzinfo=LOCAL_TIMEZONE)
                datetime.strptime(batch, "%Y%m%d%H%M")
            except ValueError as exc:
                raise RenewableInputError("新能源预测时间或批次日期无效") from exc
            if end.minute % 15:
                raise RenewableInputError("新能源预测时间必须对齐15分钟边界")
            batches.add(batch)
            if len(batches) > 1:
                raise RenewableInputError("新能源数据必须来自同一个预测批次")
            start = (end - timedelta(minutes=15)).astimezone(timezone.utc)
            stamp = start.strftime("%Y-%m-%d %H:%M:%S")
            key = (farm_id, stamp)
            if key in seen:
                raise RenewableInputError(f"farmId={farm_id}存在重复预测时间")
            seen.add(key)
            if stamp == prior_stamp:
                try:
                    previous[farm_id] = (
                        _power(
                            row.get("predictedPower"),
                            farm_id,
                            0,
                            self.validator.capacities[farm_id],
                        ),
                        f"{stamp}+00:00",
                    )
                except RenewableInputError:
                    pass
            if stamp in frames:
                frames[stamp][f"farm_{farm_id}_predictedPower"] = row.get("predictedPower")
        batch = next(iter(batches), None)
        forecast = self.validator.load(
            [frames[stamp] for stamp in axis],
            axis,
            previous=previous,
            context={"forecast_batch": batch},
        )
        digest = hashlib.sha256(f"{batch}:{forecast.payload_hash}".encode()).hexdigest()
        return RenewableForecast(
            forecast.farm_ids, forecast.values_mw, axis, digest, batch, forecast.adjustments
        )


class FileRenewableProvider:
    """Use the packaged test forecasts only for their actual forecast dates."""

    def __init__(self, directory: str | Path, capacities: Mapping[int, float]) -> None:
        self.directory = Path(directory)
        self.validator = LongTableRenewableProvider(capacities)

    def load(self, normalized_timestamps: Sequence[str]) -> RenewableForecast:
        return self.validator.load(read_forecast_files(self.directory), normalized_timestamps)
