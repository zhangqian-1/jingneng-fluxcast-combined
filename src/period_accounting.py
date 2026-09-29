"""Account for each dispatch interval using the same tariffs and events as the solver."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from src.dispatch_engine import DispatchConfig, UnitParam


def period_metrics(
    cfg: DispatchConfig,
    units: list[UnitParam],
    baseline: dict[str, Any] | None,
    solution: dict[str, Any],
    forecast: np.ndarray,
) -> list[dict[str, float]]:
    dt = cfg.dt_hour
    shares = solution["stationGridTradeShares"]

    def account(power, on, buy, sell, accepted, curtailed):
        previous = np.column_stack(([u.initial_on for u in units], on[:, :-1]))
        starts = np.maximum(on - previous, 0)
        stops = np.maximum(previous - on, 0)
        direct = (
            (power * np.array([u.gen_cost_yuan_per_kwh for u in units])[:, None]).sum(0) * 1000 * dt
        )
        gas_rates = np.array(
            [
                u.gas_price_yuan_per_m3 * u.heat_rate_mj_per_kwh / cfg.natural_gas_lhv_mj_per_nm3
                for u in units
            ]
        )
        gas = (power * gas_rates[:, None]).sum(0) * 1000 * dt
        events = (
            starts * np.array([u.start_cost_yuan for u in units])[:, None]
            + stops * np.array([u.stop_cost_yuan for u in units])[:, None]
        ).sum(0)
        grid = (
            (
                shares
                * (
                    np.array([u.buy_price_yuan_per_kwh for u in units])[:, None] * buy
                    - np.array([u.sell_price_yuan_per_kwh for u in units])[:, None] * sell
                )
            ).sum(0)
            * 1000
            * dt
        )
        carbon = (
            (power * np.array([u.gas_emission_kg_per_kwh for u in units])[:, None]).sum(0)
            + buy * cfg.grid_emission_kg_per_kwh
        ) * dt
        carbon_cost = carbon * cfg.carbon_price_yuan_per_ton
        curtail_cost = curtailed * 1000 * dt * cfg.curtail_cost_yuan_per_kwh
        return {
            "directGenerationCostYuan": direct,
            "naturalGasCostYuan": np.zeros_like(gas),
            "estimatedNaturalGasCostYuan": gas,
            "startStopCostYuan": events,
            "gridCostYuan": grid,
            "carbonCostYuan": carbon_cost,
            "curtailCostYuan": curtail_cost,
            "objectiveYuan": direct + events + grid + carbon_cost + curtail_cost,
            "carbonTon": carbon,
            "thermalMWh": power.sum(0) * dt,
            "gridBuyMWh": buy * dt,
            "renewableAcceptedMWh": accepted * dt,
            "curtailMWh": curtailed * dt,
        }

    optimized = account(
        solution["pgas"],
        solution["unitOn"],
        solution["pbuy"],
        solution["psell"],
        solution["preFarm"].sum(0),
        solution["pcurtFarm"].sum(0),
    )
    # Rolling optimization has no mandatory counterfactual plan.
    for key, series in optimized.items():
        if key in solution and not np.isclose(series.sum(), solution[key], atol=0.01, rtol=1e-8):
            raise ValueError(f"逐时段核算与求解结果不一致: {key}")
    if baseline is None:
        return [
            {
                **{k: float(v[t]) for k, v in optimized.items()},
                "renewableForecastMWh": float(forecast[:, t].sum() * dt),
            }
            for t in range(cfg.t_points)
        ]
    base_power = baseline["gasByUnitMW"].T
    base_on = (
        base_power > np.maximum(1.0, 0.5 * np.array([u.pmin for u in units]))[:, None]
    ).astype(float)
    original = account(
        base_power,
        base_on,
        baseline["buyMW"],
        baseline["sellMW"],
        baseline["renewableUseMW"],
        baseline["curtailMW"],
    )
    # A final cumulative total must reconcile to the published solver result.
    if not np.isclose(
        original["objectiveYuan"].sum(), baseline["totalCostYuan"], atol=0.01, rtol=1e-8
    ):
        raise ValueError("逐时段基准成本与汇总不一致")
    return [
        {
            **{k: float(v[t]) for k, v in optimized.items()},
            "baselineCostYuan": float(original["objectiveYuan"][t]),
            "baselineCarbonTon": float(original["carbonTon"][t]),
            "renewableForecastMWh": float(forecast[:, t].sum() * dt),
        }
        for t in range(cfg.t_points)
    ]
