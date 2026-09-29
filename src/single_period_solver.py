"""One-period HiGHS optimization initialized from measured operating history."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from src.dispatch_engine import DispatchConfig, station_grid_trade_shares
from src.errors import DispatchServiceError
from src.highs_solver import solve_with_highs
from src.input_quality import normalize_series
from src.period_accounting import period_metrics
from src.platform_config import (
    RENEWABLE_FARM_IDS,
    STATION_CODES,
    load_renewable_capacities,
    load_runtime_units,
)
from src.price_config import PRICE_FIELDS, PriceSnapshot
from src.runtime_config import REPOSITORY_ROOT
from src.single_period_models import STEP


def solve_single_period(
    actual, renewable, demand, *, day_timezone="Asia/Shanghai", price_config=None
):
    steps = 1
    if len(demand.frames) != steps or len(renewable.frames) != steps:
        raise ValueError("单断面优化只接受一个15分钟时段")
    states = [actual.thermal_state[code] for code in STATION_CODES]
    loaded = load_runtime_units(
        REPOSITORY_ROOT / "config/station_parameters.json", actual.thermal_mw
    )
    if price_config is not None:
        prices = PriceSnapshot.model_validate(price_config)
        by_code = {s.code: s.model_dump() for s in prices.stations}
        loaded = [
            replace(unit, **{k: by_code[unit.name][k] for k in PRICE_FIELDS}) for unit in loaded
        ]
    # The legacy loader clamps initial power. Single-period dispatch must use the measured value.
    units = [
        replace(unit, initial_mw=actual.thermal_mw[unit.name], initial_on=int(state.running))
        for unit, state in zip(loaded, states, strict=True)
    ]
    for unit in units:
        if unit.initial_mw > unit.pmax + 1e-5:
            raise DispatchServiceError(
                422, "ACTUAL_STATE_OUTSIDE_MODEL", "实际燃机出力超出模型范围，需核对运行参数"
            )
    wind_solar = np.array(
        [[f.power_mw[str(code)] for f in renewable.frames] for code in RENEWABLE_FARM_IDS]
    )
    capacities = load_renewable_capacities(REPOSITORY_ROOT / "config/renewable_capacities.json")
    for i, farm in enumerate(RENEWABLE_FARM_IDS):

        def validate(value, period, capacity=capacities[farm]):
            if value > capacity:
                raise ValueError("预测可用功率超过配置容量")
            return float(value)

        wind_solar[i], _ = normalize_series(
            wind_solar[i].tolist(),
            [f.timestamp.isoformat() for f in renewable.frames],
            validate,
            series=f"farm_{farm}",
            initial_upper_limit=capacities[farm],
            context={"snapshot_id": actual.snapshot_id, "forecast_id": renewable.forecast_id},
        )
    load = np.array([f.demand_mw for f in demand.frames])
    cfg = DispatchConfig(
        *(Path(".") for _ in range(7)), t_points=steps, highs_time_limit_seconds=20
    )
    # Fix settlement weights from this snapshot for both optimization and comparison.
    # These weights do not predict future station output or determine total demand.
    shares = station_grid_trade_shares(
        np.tile([actual.thermal_mw[code] for code in STATION_CODES], (steps, 1))
    )
    context = {
        "measured_at": actual.timestamp,
        "times": [f.timestamp for f in demand.frames],
        "day_timezone": day_timezone,
        "state_since": [s.state_since for s in states],
        "starts_today": [s.starts_today for s in states],
        "stops_today": [s.stops_today for s in states],
    }
    solved = solve_with_highs(load, wind_solar, units, cfg, None, shares, rolling_context=context)
    # A MILP tolerance can yield -1e-14 MW for a stopped unit. Keep the public
    # nonnegative contract and use the same normalized arrays for accounting.
    for key in ("pgas", "preFarm", "pcurtFarm", "pbuy", "psell"):
        values = np.asarray(solved[key], dtype=float)
        if not np.isfinite(values).all() or (values < -1e-7).any():
            raise RuntimeError(f"Invalid nonnegative dispatch power: {key}")
        solved[key] = np.maximum(values, 0.0)
    solved["stationGridTradeShares"] = shares
    metrics = period_metrics(cfg, units, None, solved, wind_solar)
    stamp = demand.frames[0].timestamp.isoformat()
    points = [
        {"varname": code + "_MW", "timestamp": stamp, "value": float(solved["pgas"][i, 0])}
        for i, code in enumerate(STATION_CODES)
    ]
    points += [
        {"varname": f"farm_{code}_MW", "timestamp": stamp, "value": float(solved["preFarm"][i, 0])}
        for i, code in enumerate(RENEWABLE_FARM_IDS)
    ]
    points.append({"varname": "grid_buy_MW", "timestamp": stamp, "value": float(solved["pbuy"][0])})
    if not np.isfinite([p["value"] for p in points]).all():
        raise RuntimeError("Non-finite single-period command")
    # Detailed accounting stays in the audit archive; the public result contains 27 powers.
    audit = {
        "thermal_mw": solved["pgas"].tolist(),
        "running": solved["unitOn"].tolist(),
        "renewable_mw": solved["preFarm"].tolist(),
        "grid_buy_mw": solved["pbuy"].tolist(),
        "period_metrics": metrics,
        "renewable_available_mw": wind_solar.tolist(),
        "station_grid_shares": shares.tolist(),
        "units": [vars(unit) for unit in units],
    }
    return {
        "price_version": price_config["version"] if price_config is not None else None,
        "result_point": points,
        "effective_at": stamp,
        "valid_until": (demand.frames[0].timestamp + STEP).isoformat(),
        "horizon_end": (demand.frames[-1].timestamp + STEP).isoformat(),
        "step_metrics": metrics[0],
        "horizon_metrics": {
            "objective_yuan": solved["objectiveYuan"],
            "carbon_ton": solved["carbonTon"],
        },
        "thermal_running": {
            code: bool(solved["unitOn"][i, 0]) for i, code in enumerate(STATION_CODES)
        },
        "_audit": audit,
    }
