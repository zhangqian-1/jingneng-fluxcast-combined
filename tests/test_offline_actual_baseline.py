from copy import deepcopy

import pandas as pd
import pytest

from src.dispatch_engine import dispatch_config
from src.offline_actual_baseline import actual_baselines
from src.platform_config import STATION_CODES


def example():
    axis = pd.date_range("2025-06-05 00:00:00", periods=2, freq="15min")
    histories = {
        c: pd.DataFrame(
            {"power": [200.0, 400.0] if c == "GARD" else [0.0, 0.0], "running": [c == "GARD"] * 2},
            index=axis,
        )
        for c in STATION_CODES
    }
    result = {
        "time": str(axis[1]),
        "demand_mw": 400.0,
        "actual_mw": {c: 200.0 if c == "GARD" else 0.0 for c in STATION_CODES},
    }
    return histories, result


def test_reference_uses_same_period_not_previous_snapshot_and_no_double_fuel_charge():
    histories, result = example()
    cfg = dispatch_config()
    reference = actual_baselines(cfg, histories, [result])[0]
    metric = reference["metrics"]
    assert reference["thermal_mw"]["GARD"] == 400.0
    assert metric["thermalMWh"] == 100.0  # 400 MW * 0.25 h, not the 200 MW initial value.
    assert metric["directGenerationCostYuan"] == pytest.approx(48000.0)
    assert metric["carbonTon"] == pytest.approx(30.294)
    assert metric["objectiveYuan"] == pytest.approx(48000 + 30.294 * cfg.carbon_price_yuan_per_ton)
    assert metric["naturalGasCostYuan"] == metric["curtailCostYuan"] == 0.0


def test_different_supply_and_missing_actuals_cannot_create_savings():
    histories, result = example()
    wrong = deepcopy(result)
    wrong["demand_mw"] = 500.0
    with pytest.raises(ValueError, match="供电量"):
        actual_baselines(dispatch_config(), histories, [wrong])
    histories["GARD"].iloc[1, 0] = float("nan")
    with pytest.raises(ValueError, match="数据缺失"):
        actual_baselines(dispatch_config(), histories, [result])


def test_observed_start_counted_once_at_target_interval():
    histories, result = example()
    histories["GARD"].iloc[0] = [0.0, False]
    result["actual_mw"]["GARD"] = 0.0
    metric = actual_baselines(dispatch_config(), histories, [result])[0]["metrics"]
    assert metric["startStopCostYuan"] == 300000.0
