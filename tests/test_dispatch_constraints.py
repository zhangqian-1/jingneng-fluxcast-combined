from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import src.dispatch_engine as dispatch_engine
from src.dispatch_engine import (
    daily_transition_limits,
    interval_ramp_limits_mw,
    read_pre_horizon_points,
)


def test_jfrd_startup_ramp_can_reach_its_online_minimum() -> None:
    """A 15-minute start must not be made infeasible by the normal 13 MW/min ramp."""
    jfrd = SimpleNamespace(pmin=205.0, ramp_mw_per_min=13.0)

    normal, startup, shutdown = interval_ramp_limits_mw(jfrd, dt_min=15.0)

    assert normal == 195.0
    assert startup == 205.0
    assert shutdown == 205.0


def test_initially_online_station_still_has_one_restart_available() -> None:
    """Being online before midnight is a state, not a start event within the new day."""
    unit = SimpleNamespace(initial_on=1, max_start_per_day=1)

    assert daily_transition_limits(unit) == (1, 1)


def test_pre_horizon_state_comes_from_last_measurement_before_midnight(tmp_path) -> None:
    source = tmp_path / "station.csv"
    pd.DataFrame(
        {
            "ts": [
                "2025-06-04 23:30:00",
                "2025-06-04 23:45:00",
                "2025-06-05 00:00:00",
                "2025-06-05 00:15:00",
            ],
            "P1": [0.0, 205.0, 0.0, 0.0],
        }
    ).to_csv(source, index=False)

    previous = read_pre_horizon_points(source, ["P1"], "2025-06-05")

    assert float(previous["P1"]) == 205.0


def test_default_natural_gas_lhv_uses_beijing_power_standard_value() -> None:
    field = dispatch_engine.DispatchConfig.__dataclass_fields__["natural_gas_lhv_mj_per_nm3"]

    assert field.default == pytest.approx(38.931)


def test_station_marginal_cost_includes_fuel_once() -> None:
    unit = SimpleNamespace(
        gen_cost_yuan_per_kwh=0.48,
        gas_price_yuan_per_m3=2.64,
        heat_rate_mj_per_kwh=5.4,
    )

    cost = dispatch_engine.station_marginal_cost_yuan_per_kwh(unit, lhv_mj_per_nm3=38.931)

    assert cost == pytest.approx(0.48)
    unit.gas_price_yuan_per_m3 = 100
    assert dispatch_engine.station_marginal_cost_yuan_per_kwh(unit, 38.931) == cost


def test_station_grid_trade_shares_follow_each_station_load() -> None:
    station_load_mw = np.array(
        [
            [75.0, 25.0],
            [20.0, 80.0],
        ]
    )

    shares = dispatch_engine.station_grid_trade_shares(station_load_mw)

    np.testing.assert_allclose(shares, [[0.75, 0.20], [0.25, 0.80]])
    np.testing.assert_allclose(shares.sum(axis=0), np.ones(2))


def test_grid_cost_uses_each_station_price_instead_of_arithmetic_mean() -> None:
    station_load_mw = np.array(
        [
            [75.0, 25.0],
            [20.0, 80.0],
        ]
    )
    shares = dispatch_engine.station_grid_trade_shares(station_load_mw)
    units = [
        SimpleNamespace(buy_price_yuan_per_kwh=0.5, sell_price_yuan_per_kwh=0.4),
        SimpleNamespace(buy_price_yuan_per_kwh=0.7, sell_price_yuan_per_kwh=0.8),
    ]

    cost = dispatch_engine.station_grid_cost_yuan(
        buy_mw=np.array([40.0, 0.0]),
        sell_mw=np.array([0.0, 10.0]),
        station_shares=shares,
        units=units,
        dt_hour=0.25,
    )

    # Purchase: (30 MW * 0.5 + 10 MW * 0.7) * 0.25 h * 1000.
    # Sale revenue: (2 MW * 0.4 + 8 MW * 0.8) * 0.25 h * 1000.
    assert cost == pytest.approx(3700.0)
