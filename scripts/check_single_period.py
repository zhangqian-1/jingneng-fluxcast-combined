"""Offline one-period feasibility study using supplied data, never an execution feed."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dispatch_engine import (  # noqa: E402
    GAS_POINTS,
    dispatch_config,
    interval_ramp_limits_mw,
    read_renewable_forecast,
    station_grid_trade_shares,
)
from src.highs_solver import solve_with_highs  # noqa: E402
from src.input_quality import write_work_log  # noqa: E402
from src.period_accounting import period_metrics  # noqa: E402
from src.platform_config import STATION_CODES, load_runtime_units  # noqa: E402


def read_history(cfg):
    histories = {}
    for code, filename, points in GAS_POINTS:
        frame = pd.read_csv(cfg.data_dir / filename, usecols=["ts", *points])
        stamps = pd.to_datetime(frame.pop("ts"))
        if stamps.duplicated().any():
            raise ValueError(f"Duplicate timestamps: {code}")
        frame.index = stamps
        beginning = pd.Timestamp(cfg.load_day)
        frame = frame.loc[
            beginning - pd.Timedelta(days=7) : beginning + pd.Timedelta(hours=23, minutes=45)
        ]
        invalid = ~np.isfinite(frame.to_numpy()).all(axis=1)
        if invalid.any():
            last_invalid = frame.index[invalid][-1]
            if last_invalid >= beginning - pd.Timedelta(hours=6, minutes=15):
                raise ValueError(f"Missing measurements near study window: {code}")
            frame = frame.loc[frame.index > last_invalid]
        if not frame.index.equals(pd.date_range(frame.index[0], frame.index[-1], freq="15min")):
            raise ValueError(f"Discontinuous measurement history: {code}")
        # Matches the existing offline regression's nonnegative measurement convention.
        power = frame.clip(lower=0).sum(axis=1).sort_index()
        on = power > 1.0  # An offline estimate, not an authoritative run-state signal.
        changed = on.ne(on.shift())
        since = pd.Series(power.index, index=power.index).where(changed).ffill()
        starts = (on & ~on.shift(fill_value=on.iloc[0])).astype(int)
        stops = (~on & on.shift(fill_value=on.iloc[0])).astype(int)
        histories[code] = pd.DataFrame(
            {
                "power": power,
                "running": on,
                "since": since,
                "starts": starts.groupby(power.index.date).cumsum(),
                "stops": stops.groupby(power.index.date).cumsum(),
            }
        )
    return histories


def solve_case(cfg, histories, target, demand, renewable, steps):
    if steps != 1:
        raise ValueError("Only independent single-period studies are supported")
    measured = target - pd.Timedelta(minutes=15)
    observed = {code: histories[code].loc[measured] for code in STATION_CODES}
    actual = {code: float(observed[code]["power"]) for code in STATION_CODES}
    units = load_runtime_units(ROOT / "config/station_parameters.json", actual)
    units = [
        replace(u, initial_mw=actual[u.name], initial_on=int(observed[u.name]["running"]))
        for u in units
    ]
    if any(u.initial_mw > u.pmax + 1e-5 for u in units):
        raise ValueError("Historical measured power exceeds current model range")
    context = {
        # Localizing the timezone-free archive is an explicit offline scenario assumption.
        "measured_at": measured.tz_localize("Asia/Shanghai"),
        "times": list(pd.date_range(target, periods=steps, freq="15min", tz="Asia/Shanghai")),
        "day_timezone": "Asia/Shanghai",
        "state_since": [observed[c]["since"].tz_localize("Asia/Shanghai") for c in STATION_CODES],
        "starts_today": [int(observed[c]["starts"]) for c in STATION_CODES],
        "stops_today": [int(observed[c]["stops"]) for c in STATION_CODES],
    }
    # Import capability is based on this single target interval.
    grid_limit = float(demand[0]) * cfg.grid_limit_ratio
    case_cfg = replace(
        cfg,
        t_points=steps,
        grid_limit_ratio=grid_limit / float(np.max(demand)) if np.max(demand) else 0.0,
        highs_time_limit_seconds=20,
    )
    shares = station_grid_trade_shares(np.tile(list(actual.values()), (steps, 1)))
    begin = time.perf_counter()
    solved = solve_with_highs(
        demand, renewable, units, case_cfg, None, shares, rolling_context=context
    )
    elapsed = time.perf_counter() - begin
    solved["stationGridTradeShares"] = shares
    metrics = period_metrics(case_cfg, units, None, solved, renewable)
    balance = solved["pgas"].sum(0) + solved["preFarm"].sum(0) + solved["pbuy"] - demand
    max_ramp_violation = 0.0
    for i, u in enumerate(units):
        ramp, start_ramp, stop_ramp = interval_ramp_limits_mw(u, 15)
        previous = np.r_[u.initial_mw, solved["pgas"][i, :-1]]
        previous_on = np.r_[u.initial_on, solved["unitOn"][i, :-1]]
        starts = np.maximum(solved["unitOn"][i] - previous_on, 0)
        stops = np.maximum(previous_on - solved["unitOn"][i], 0)
        max_ramp_violation = max(
            max_ramp_violation,
            float(np.max(solved["pgas"][i] - previous - ramp - starts * (start_ramp - ramp))),
            float(np.max(previous - solved["pgas"][i] - ramp - stops * (stop_ramp - ramp))),
        )
    return {
        "time": str(target),
        "steps": steps,
        "seconds": elapsed,
        "demand_mw": float(demand[0]),
        "renewable_available_mw": float(renewable[:, 0].sum()),
        "renewable_accepted_mw": float(solved["preFarm"][:, 0].sum()),
        "farm_available_mw": renewable[:, 0].tolist(),
        "farm_accepted_mw": solved["preFarm"][:, 0].tolist(),
        "grid_buy_mw": float(solved["pbuy"][0]),
        "grid_limit_mw": grid_limit,
        "thermal_mw": dict(zip(STATION_CODES, solved["pgas"][:, 0].tolist(), strict=True)),
        "actual_mw": actual,
        "thermal_running": dict(zip(STATION_CODES, solved["unitOn"][:, 0].tolist(), strict=True)),
        "step_metrics": metrics[0],
        "max_balance_error_mw": float(np.max(np.abs(balance))),
        "max_ramp_violation_mw": max_ramp_violation,
        "history_is_estimated": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "output/single-period-study-20260923-single"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["WORK_LOG_PATH"] = str(output / "work.jsonl")
    cfg = dispatch_config(output_dir=output)
    histories = read_history(cfg)
    axis = pd.date_range(cfg.load_day, periods=96, freq="15min")
    # Legacy equivalent-demand scenario ONLY; it is not an independent load forecast.
    demand = sum(histories[c].loc[axis, "power"].to_numpy() for c in STATION_CODES)
    _, renewable, _ = read_renewable_forecast(cfg)
    results, failures = [], []
    for t, target in enumerate(axis):
        for steps in (1,):
            if t + steps > len(axis):
                continue
            try:
                item = solve_case(
                    cfg,
                    histories,
                    target,
                    demand[t : t + steps],
                    renewable[:, t : t + steps],
                    steps,
                )
                results.append(item)
                write_work_log({"stage": "single_period_study", "action": "completed", **item})
            except (ValueError, RuntimeError, KeyError) as exc:
                failure = {"time": str(target), "steps": steps, "reason": str(exc)}
                failures.append(failure)
                write_work_log({"stage": "single_period_study", "action": "failed", **failure})
        if (t + 1) % 16 == 0:
            print(json.dumps({"processed": t + 1, "single_ok": len(results)}), flush=True)
    summary = {
        "data_kind": "mixed_date_offline_scenario_not_live",
        "thermal_history_day": cfg.load_day,
        "renewable_day": cfg.renewable_day,
        "demand_source": "historical_seven_station_sum_regression_only",
        "state_source": "estimated_from_power_threshold_1MW_not_authoritative",
        "single_attempted": 96,
        "single_succeeded": len(results),
        "max_balance_error_mw": max((r["max_balance_error_mw"] for r in results), default=None),
        "max_ramp_violation_mw": max((r["max_ramp_violation_mw"] for r in results), default=None),
        "single_solve_seconds_median": float(np.median([r["seconds"] for r in results])),
        "single_solve_seconds_max": max((r["seconds"] for r in results), default=None),
    }
    document = {
        "summary": summary,
        "single_period": results,
        "failures": failures,
    }
    (output / "results.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    records = [
        {
            "time": r["time"],
            "demand_MW": r["demand_mw"],
            **{f"{c}_MW": r["thermal_mw"][c] for c in STATION_CODES},
            "renewable_MW": r["renewable_accepted_mw"],
            "grid_buy_MW": r["grid_buy_mw"],
            **r["step_metrics"],
        }
        for r in results
    ]
    pd.DataFrame(records).to_csv(output / "单断面试算明细.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
