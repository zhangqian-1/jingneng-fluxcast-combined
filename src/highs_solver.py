"""License-free MILP backend for the existing station-aggregate dispatch model.

Uses scipy.optimize.milp (HiGHS). Only solutions certified optimal within cfg.mip_gap are accepted.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from src.dispatch_engine import (
    DispatchConfig,
    UnitParam,
    daily_transition_limits,
    interval_ramp_limits_mw,
)


def solve_with_highs(
    demand_mw: np.ndarray,
    farm_forecast_mw: np.ndarray,
    units: list[UnitParam],
    cfg: DispatchConfig,
    baseline: dict[str, Any] | None,
    station_grid_shares: np.ndarray,
    *,
    rolling_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    periods, dt = cfg.t_points, cfg.dt_hour
    time_limit = float(cfg.highs_time_limit_seconds)
    if not np.isfinite(time_limit) or time_limit <= 0:
        raise ValueError("HiGHS time limit must be a positive finite number")
    n_units, n_farms = len(units), farm_forecast_mw.shape[0]
    grid_max = cfg.grid_limit_ratio * float(demand_mw.max())
    size = 0

    def variables(shape):
        nonlocal size
        count = int(np.prod(shape))
        indices = np.arange(size, size + count).reshape(shape)
        size += count
        return indices

    pgas, on, start, stop = [variables((n_units, periods)) for _ in range(4)]
    accepted, curtailed = [variables((n_farms, periods)) for _ in range(2)]
    buy, sell = [variables((periods,)) for _ in range(2)]
    upper = np.full(size, np.inf)
    integral = np.zeros(size, dtype=int)
    for indices in (on, start, stop):
        integral[indices] = 1
        upper[indices] = 1.0
    upper[buy] = grid_max
    upper[sell] = 0.0  # Import-only grid connection; retained in the result schema.
    upper[accepted] = farm_forecast_mw
    upper[curtailed] = farm_forecast_mw

    row_indices, col_indices, coefficients = [], [], []
    lower_rows, upper_rows = [], []

    def constraint(terms, lower=-np.inf, upper=np.inf):
        row = len(lower_rows)
        for index, coefficient in terms:
            row_indices.append(row)
            col_indices.append(int(index))
            coefficients.append(float(coefficient))
        lower_rows.append(float(lower))
        upper_rows.append(float(upper))

    for f in range(n_farms):
        for t in range(periods):
            forecast = float(farm_forecast_mw[f, t])
            constraint([(accepted[f, t], 1), (curtailed[f, t], 1)], forecast, forecast)
    for t in range(periods):
        gas_terms = [(pgas[i, t], 1) for i in range(n_units)]
        constraint(
            gas_terms
            + [(accepted[f, t], 1) for f in range(n_farms)]
            + [(buy[t], 1), (sell[t], -1)],
            demand_mw[t],
            demand_mw[t],
        )
        constraint(gas_terms + [(buy[t], 1)], upper=demand_mw[t])

    for i, unit in enumerate(units):
        ramp, startup_ramp, shutdown_ramp = interval_ramp_limits_mw(unit, dt * 60)
        start_limit, stop_limit = daily_transition_limits(unit)
        min_up = max(1, int(np.ceil(unit.min_up_hour / dt)))
        min_down = max(1, int(np.ceil(unit.min_down_hour / dt)))
        if rolling_context is None:
            constraint([(j, 1) for j in start[i]], upper=start_limit)
            constraint([(j, 1) for j in stop[i]], upper=stop_limit)
        else:
            zone = ZoneInfo(rolling_context["day_timezone"])
            observed_day = rolling_context["measured_at"].astimezone(zone).date()
            days = [stamp.astimezone(zone).date() for stamp in rolling_context["times"]]
            for day in set(days):
                indices = [t for t, value in enumerate(days) if value == day]
                used_start = rolling_context["starts_today"][i] if day == observed_day else 0
                used_stop = rolling_context["stops_today"][i] if day == observed_day else 0
                constraint(
                    [(start[i, t], 1) for t in indices], upper=max(0, start_limit - used_start)
                )
                constraint([(stop[i, t], 1) for t in indices], upper=max(0, stop_limit - used_stop))
            minimum = unit.min_up_hour if unit.initial_on else unit.min_down_hour
            for t, stamp in enumerate(rolling_context["times"]):
                elapsed = (stamp - rolling_context["state_since"][i]).total_seconds() / 3600
                if elapsed < minimum - 1e-9:
                    constraint([(on[i, t], 1)], unit.initial_on, unit.initial_on)
        for t in range(periods):
            constraint([(pgas[i, t], 1), (on[i, t], -unit.pmin)], lower=0)
            constraint([(pgas[i, t], 1), (on[i, t], -unit.pmax)], upper=0)
            constraint(
                [(start[i, k], 1) for k in range(max(0, t - min_up + 1), t + 1)] + [(on[i, t], -1)],
                upper=0,
            )
            constraint(
                [(stop[i, k], 1) for k in range(max(0, t - min_down + 1), t + 1)] + [(on[i, t], 1)],
                upper=1,
            )
            # Exact binary state transition; simultaneous start/stop is forbidden.
            transition = [(on[i, t], 1), (start[i, t], -1), (stop[i, t], 1)]
            if t:
                transition.append((on[i, t - 1], -1))
            initial_on = unit.initial_on if t == 0 else 0
            constraint(transition, initial_on, initial_on)
            constraint([(start[i, t], 1), (stop[i, t], 1)], upper=1)
            up = [(pgas[i, t], 1), (start[i, t], -(startup_ramp - ramp))]
            down = [(pgas[i, t], -1), (stop[i, t], -(shutdown_ramp - ramp))]
            if t:
                up.append((pgas[i, t - 1], -1))
                down.append((pgas[i, t - 1], 1))
            initial_mw = unit.initial_mw if t == 0 else 0
            constraint(up, upper=ramp + initial_mw)
            constraint(down, upper=ramp - initial_mw)

    # Separate cost vectors preserve the public KPI contract and avoid double counting.
    components = {}
    for name in (
        "directGenerationCostYuan",
        "naturalGasCostYuan",
        "startStopCostYuan",
        "gridCostYuan",
        "curtailCostYuan",
        "carbonCostYuan",
    ):
        components[name] = np.zeros(size)
    carbon = np.zeros(size)
    estimated_gas = np.zeros(size)
    for i, unit in enumerate(units):
        components["directGenerationCostYuan"][pgas[i]] = unit.gen_cost_yuan_per_kwh * 1000 * dt
        estimated_gas[pgas[i]] = (
            unit.gas_price_yuan_per_m3
            * unit.heat_rate_mj_per_kwh
            / cfg.natural_gas_lhv_mj_per_nm3
            * 1000
            * dt
        )
        components["startStopCostYuan"][start[i]] = unit.start_cost_yuan
        components["startStopCostYuan"][stop[i]] = unit.stop_cost_yuan
        components["gridCostYuan"][buy] += (
            unit.buy_price_yuan_per_kwh * station_grid_shares[i] * 1000 * dt
        )
        components["gridCostYuan"][sell] -= (
            unit.sell_price_yuan_per_kwh * station_grid_shares[i] * 1000 * dt
        )
        carbon[pgas[i]] = unit.gas_emission_kg_per_kwh * dt
    carbon[buy] = cfg.grid_emission_kg_per_kwh * dt
    components["curtailCostYuan"][curtailed] = cfg.curtail_cost_yuan_per_kwh * 1000 * dt
    components["carbonCostYuan"] = carbon * cfg.carbon_price_yuan_per_ton
    if baseline is not None:
        constraint(
            [(int(j), carbon[j]) for j in np.flatnonzero(carbon)], upper=baseline["carbonTon"]
        )
    objective = sum(components.values())
    matrix = coo_matrix(
        (coefficients, (row_indices, col_indices)), shape=(len(lower_rows), size)
    ).tocsc()
    lower_rows, upper_rows = np.asarray(lower_rows), np.asarray(upper_rows)
    result = milp(
        objective,
        integrality=integral,
        bounds=Bounds(np.zeros(size), upper),
        constraints=LinearConstraint(matrix, lower_rows, upper_rows),
        options={"time_limit": time_limit, "mip_rel_gap": cfg.mip_gap},
    )
    if result.status != 0 or result.x is None:
        raise RuntimeError(f"HiGHS solve failed, status={result.status}: {result.message}")
    x = np.asarray(result.x)
    # Validate all rows, bounds and integrality before producing dispatch commands.
    activity = matrix @ x
    tolerance = 1e-5
    if (
        not np.isfinite(x).all()
        or (x < -tolerance).any()
        or (x > upper + tolerance).any()
        or (activity < lower_rows - tolerance).any()
        or (activity > upper_rows + tolerance).any()
        or (np.abs(x[integral == 1] - np.rint(x[integral == 1])) > tolerance).any()
    ):
        raise RuntimeError("HiGHS returned a solution violating dispatch constraints")
    costs = {name: float(vector @ x) for name, vector in components.items()}
    return {
        "solverMode": "highs",
        "objectiveYuan": float(objective @ x),
        **costs,
        "fuelCostYuan": costs["directGenerationCostYuan"],
        "estimatedNaturalGasCostYuan": float(estimated_gas @ x),
        "carbonTon": float(carbon @ x),
        "pgas": x[pgas],
        "unitOn": np.rint(x[on]),
        "preFarm": x[accepted],
        "pcurtFarm": x[curtailed],
        "pbuy": x[buy],
        "psell": x[sell],
    }
