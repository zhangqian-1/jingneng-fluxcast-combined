from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_period_start_stop_cost_is_booked_at_the_event():
    from types import SimpleNamespace

    import numpy as np

    from src.period_accounting import period_metrics

    cfg = SimpleNamespace(
        dt_hour=0.25,
        t_points=3,
        natural_gas_lhv_mj_per_nm3=6,
        grid_emission_kg_per_kwh=0.5,
        carbon_price_yuan_per_ton=5,
        curtail_cost_yuan_per_kwh=0.6,
    )
    unit = SimpleNamespace(
        initial_on=0,
        pmin=10,
        gen_cost_yuan_per_kwh=2,
        gas_price_yuan_per_m3=3,
        heat_rate_mj_per_kwh=4,
        start_cost_yuan=100,
        stop_cost_yuan=30,
        buy_price_yuan_per_kwh=0.5,
        sell_price_yuan_per_kwh=0,
        gas_emission_kg_per_kwh=0.4,
    )
    zero = np.zeros(3)
    baseline = dict(
        gasByUnitMW=np.zeros((3, 1)),
        buyMW=zero,
        sellMW=zero,
        renewableUseMW=zero,
        curtailMW=zero,
        totalCostYuan=0,
    )
    solution = dict(
        pgas=np.array([[0, 20, 0]]),
        unitOn=np.array([[0, 1, 0]]),
        pbuy=zero,
        psell=zero,
        preFarm=np.zeros((1, 3)),
        pcurtFarm=np.zeros((1, 3)),
        stationGridTradeShares=np.ones((1, 3)),
    )
    periods = period_metrics(cfg, [unit], baseline, solution, np.zeros((1, 3)))
    assert [p["startStopCostYuan"] for p in periods] == [0, 100, 30]
    assert periods[1]["directGenerationCostYuan"] == 10000
    assert periods[1]["naturalGasCostYuan"] == 0
    assert periods[1]["estimatedNaturalGasCostYuan"] == 10000
    assert periods[1]["carbonTon"] == 2
    assert periods[1]["objectiveYuan"] == 10110
