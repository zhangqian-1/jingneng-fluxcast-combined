"""Measured snapshots and one-period forecasts and reference plans (UTC)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from src.platform_config import RENEWABLE_FARM_IDS, STATION_CODES

STEP = timedelta(minutes=15)


def utc_time(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("时间必须为ISO日期时间，不能使用数值时间戳")
    stamp = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    try:
        return stamp.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("时区换算超出支持的日期范围") from exc


def nonnegative(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("功率必须为有限非负数值")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError("功率超过数值范围") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError("功率必须为有限非负数值")
    return value


Power = Annotated[float, BeforeValidator(nonnegative)]
UtcTime = Annotated[datetime, BeforeValidator(utc_time)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def fleet_keys(values, expected):
    if set(values) != set(expected):
        raise ValueError("必须完整覆盖约定的场站，不得缺少或重复添加场站")
    return values


class ThermalState(StrictModel):
    running: bool = Field(strict=True)
    state_since: UtcTime
    starts_today: int = Field(ge=0, strict=True)
    stops_today: int = Field(ge=0, strict=True)


class ActualSnapshot(StrictModel):
    snapshot_id: Identifier
    timestamp: UtcTime
    thermal_mw: dict[str, Power]
    renewable_mw: dict[str, Power] | None = None
    thermal_state: dict[str, ThermalState]
    state_basis: Literal["reported", "power_history_estimate"] = "reported"

    @field_validator("thermal_mw")
    @classmethod
    def thermal_keys(cls, value):
        return fleet_keys(value, STATION_CODES)

    @field_validator("renewable_mw")
    @classmethod
    def renewable_keys(cls, value):
        return None if value is None else fleet_keys(value, map(str, RENEWABLE_FARM_IDS))

    @model_validator(mode="after")
    def check_snapshot(self):
        if self.timestamp.minute % 15 or self.timestamp.second or self.timestamp.microsecond:
            raise ValueError("实际断面时间必须在15分钟边界")
        if self.thermal_state is not None:
            fleet_keys(self.thermal_state, STATION_CODES)
            for code, state in self.thermal_state.items():
                if state.state_since > self.timestamp:
                    raise ValueError("状态开始时间不能晚于实际断面")
                if not state.running and self.thermal_mw[code] > 1.0:
                    raise ValueError("停机状态与实际功率不一致")
        return self


class PowerFrame(StrictModel):
    timestamp: UtcTime
    power_mw: dict[str, Power]


class DemandFrame(StrictModel):
    timestamp: UtcTime
    demand_mw: Power


class ForecastBase(StrictModel):
    snapshot_id: Identifier
    forecast_id: Identifier
    issued_at: UtcTime

    def validate_axis(self):
        stamps = [f.timestamp for f in self.frames]
        first = stamps[0]
        if first.minute % 15 or first.second or first.microsecond:
            raise ValueError("预测时间必须在15分钟边界")
        try:
            expected = [first + n * STEP for n in range(len(self.frames))]
            first + len(self.frames) * STEP  # Final interval end must be representable.
        except OverflowError as exc:
            raise ValueError("预测窗口超出支持的日期范围") from exc
        if stamps != expected:
            raise ValueError("预测必须为连续的15分钟时段")
        if self.issued_at >= first:
            raise ValueError("预测发布必须早于计划生效时刻")
        return self


class PlanFrame(StrictModel):
    timestamp: UtcTime
    thermal_mw: dict[str, Power]
    thermal_running: dict[str, Annotated[bool, Field(strict=True)]]
    renewable_mw: dict[str, Power]
    grid_buy_mw: Power

    @model_validator(mode="after")
    def check_fleet(self):
        fleet_keys(self.thermal_mw, STATION_CODES)
        fleet_keys(self.thermal_running, STATION_CODES)
        fleet_keys(self.renewable_mw, map(str, RENEWABLE_FARM_IDS))
        return self


class SingleReferencePlan(StrictModel):
    snapshot_id: Identifier
    plan_id: Identifier
    issued_at: UtcTime
    frames: list[PlanFrame] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def check_axis(self):
        return ForecastBase.validate_axis(self)


class SingleRenewableForecast(ForecastBase):
    frames: list[PowerFrame] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def check_forecast(self):
        self.validate_axis()
        for frame in self.frames:
            fleet_keys(frame.power_mw, map(str, RENEWABLE_FARM_IDS))
        return self


class SingleDemandForecast(ForecastBase):
    frames: list[DemandFrame] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def check_forecast(self):
        return self.validate_axis()
