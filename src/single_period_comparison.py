"""Account for an optional original plan without calling or constraining the solver."""

from pathlib import Path

import numpy as np

from src.dispatch_engine import DispatchConfig, UnitParam
from src.period_accounting import period_metrics
from src.platform_config import RENEWABLE_FARM_IDS, STATION_CODES
from src.single_period_models import utc_time


def compare_plan(plan, inputs, archive, *, include_periods=False):
    audit = archive["_audit"]
    if not {"units", "renewable_available_mw", "station_grid_shares"}.issubset(audit):
        raise ValueError("旧版结果缺少同口径核算信息，请使用新断面生成结果")
    frames = plan["frames"]
    demands = inputs["demand_forecast"]["frames"]
    if [utc_time(f["timestamp"]) for f in frames] != [utc_time(f["timestamp"]) for f in demands]:
        raise ValueError("原调度计划与本轮预测时段不一致")
    units = [UnitParam(**u) for u in audit["units"]]
    power = np.array([[f["thermal_mw"][code] for f in frames] for code in STATION_CODES])
    on = np.array(
        [[f["thermal_running"][code] for f in frames] for code in STATION_CODES], dtype=float
    )
    renewable = np.array(
        [[f["renewable_mw"][str(code)] for f in frames] for code in RENEWABLE_FARM_IDS]
    )
    available = np.array(audit["renewable_available_mw"])
    buy = np.array([f["grid_buy_mw"] for f in frames])
    load = np.array([f["demand_mw"] for f in demands])
    if not np.allclose(power.sum(0) + renewable.sum(0) + buy, load, atol=1e-5, rtol=0):
        raise ValueError("原调度计划未满足同一供电需求，无法进行同口径对比")
    if (renewable > available + 1e-5).any():
        raise ValueError("原调度计划的风光接纳量超过本轮可用预测")
    if (power > np.array([u.pmax for u in units])[:, None] * on + 1e-5).any() or (
        power < np.array([u.pmin for u in units])[:, None] * on - 1e-5
    ).any():
        raise ValueError("原调度计划的出力与运行状态或出力范围不一致")
    cfg = DispatchConfig(*(Path(".") for _ in range(7)), t_points=len(frames))
    if (buy > cfg.grid_limit_ratio * load.max() + 1e-5).any():
        raise ValueError("原调度计划购电超过本轮模型上限")
    original = period_metrics(
        cfg,
        units,
        None,
        {
            "pgas": power,
            "unitOn": on,
            "pbuy": buy,
            "psell": np.zeros(len(frames)),
            "preFarm": renewable,
            "pcurtFarm": np.maximum(available - renewable, 0),
            "stationGridTradeShares": np.array(audit["station_grid_shares"]),
        },
        available,
    )
    optimized = audit["period_metrics"]
    step = {
        "baselineCostYuan": original[0]["objectiveYuan"],
        "baselineCarbonTon": original[0]["carbonTon"],
        "costSavingYuan": original[0]["objectiveYuan"] - optimized[0]["objectiveYuan"],
        "carbonReductionTon": original[0]["carbonTon"] - optimized[0]["carbonTon"],
    }
    base_cost = sum(m["objectiveYuan"] for m in original)
    base_carbon = sum(m["carbonTon"] for m in original)
    result = {
        "status": "available",
        "plan_id": plan["plan_id"],
        "step_metrics": step,
        "horizon_metrics": {
            "baseline_cost_yuan": base_cost,
            "baseline_carbon_ton": base_carbon,
            "cost_saving_yuan": base_cost - archive["horizon_metrics"]["objective_yuan"],
            "carbon_reduction_ton": base_carbon - archive["horizon_metrics"]["carbon_ton"],
        },
    }
    if include_periods:
        result["period_metrics"] = original
    return result
