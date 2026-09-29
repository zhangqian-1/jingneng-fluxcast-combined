"""Physical constraints and billing for the one-period solver."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import src.highs_solver as backend
from src.dispatch_engine import DispatchConfig
from src.platform_config import STATION_CODES, load_runtime_units

ROOT = Path(__file__).resolve().parents[1]


def solve_case(tmp_path, *, running=False, since_hours=5, starts=0, stamp=None, gas_price=3.0):
    stamp = stamp or datetime(2026, 9, 21, 10, tzinfo=timezone.utc)
    unit = load_runtime_units(
        ROOT / "config/station_parameters.json", dict.fromkeys(STATION_CODES, 0)
    )[0]
    unit = replace(
        unit,
        pmin=10,
        pmax=100,
        initial_mw=20 if running else 0,
        initial_on=int(running),
        gen_cost_yuan_per_kwh=5 if running else 0,
        start_cost_yuan=0,
        stop_cost_yuan=0,
        min_up_hour=6,
        min_down_hour=2,
        gas_price_yuan_per_m3=gas_price,
    )
    cfg = DispatchConfig(*(tmp_path for _ in range(7)), t_points=1, grid_limit_ratio=1.0)
    context = {
        "measured_at": stamp,
        "times": [stamp + timedelta(minutes=15)],
        "state_since": [stamp - timedelta(hours=since_hours)],
        "starts_today": [starts],
        "stops_today": [0],
        "day_timezone": "UTC",
    }
    result = backend.solve_with_highs(
        np.array([20.0]),
        np.zeros((1, 1)),
        [unit],
        cfg,
        None,
        np.ones((1, 1)),
        rolling_context=context,
    )
    return result, unit, cfg


def test_recent_start_remains_online(tmp_path):
    result, _, _ = solve_case(tmp_path, running=True, since_hours=0.5)
    assert result["unitOn"][0, 0] == 1
    assert result["pgas"][0, 0] >= 10 - 1e-5


def test_recent_stop_cannot_restart(tmp_path):
    result, _, _ = solve_case(tmp_path, since_hours=0.5)
    assert result["unitOn"][0, 0] == 0
    assert result["pbuy"][0] == pytest.approx(20)


def test_daily_start_budget_is_inherited(tmp_path):
    result, _, _ = solve_case(tmp_path, starts=1)
    assert result["unitOn"][0, 0] == 0


def test_daily_budget_resets_at_target_business_midnight(tmp_path):
    result, _, _ = solve_case(
        tmp_path, starts=1, stamp=datetime(2026, 9, 21, 23, 45, tzinfo=timezone.utc)
    )
    assert result["unitOn"][0, 0] == 1
    assert result["pgas"][0, 0] == pytest.approx(20)


def test_solver_timeout_never_publishes_incumbent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backend,
        "milp",
        lambda *a, **k: SimpleNamespace(status=1, message="timeout", x=np.zeros(100)),
    )
    with pytest.raises(RuntimeError, match="status=1"):
        solve_case(tmp_path)


def test_fuel_is_not_billed_twice(tmp_path):
    from src.period_accounting import period_metrics

    outcomes = []
    for price in (3.0, 30.0):
        result, unit, cfg = solve_case(tmp_path, running=True, since_hours=0.5, gas_price=price)
        result["stationGridTradeShares"] = np.ones((1, 1))
        metric = period_metrics(cfg, [unit], None, result, np.zeros((1, 1)))[0]
        assert metric["naturalGasCostYuan"] == 0
        assert metric["directGenerationCostYuan"] == pytest.approx(
            result["pgas"][0, 0] * 250 * unit.gen_cost_yuan_per_kwh
        )
        outcomes.append(metric)
    assert outcomes[1]["objectiveYuan"] == pytest.approx(outcomes[0]["objectiveYuan"])
    assert outcomes[1]["estimatedNaturalGasCostYuan"] == pytest.approx(
        outcomes[0]["estimatedNaturalGasCostYuan"] * 10
    )


def test_surplus_renewable_is_curtailed_not_exported(tmp_path):
    unit = load_runtime_units(
        ROOT / "config/station_parameters.json", dict.fromkeys(STATION_CODES, 0)
    )[0]
    unit = replace(
        unit, pmin=10, pmax=100, initial_mw=0, initial_on=0, sell_price_yuan_per_kwh=1000
    )
    cfg = DispatchConfig(*(tmp_path for _ in range(7)), t_points=1)
    result = backend.solve_with_highs(
        np.array([100.0]), np.array([[190.0]]), [unit], cfg, None, np.ones((1, 1))
    )
    assert result["psell"][0] == 0
    assert result["pbuy"][0] == 0
    assert result["preFarm"][0, 0] == pytest.approx(100)
    assert result["pcurtFarm"][0, 0] == pytest.approx(90)
