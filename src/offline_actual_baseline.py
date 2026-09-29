"""Same-period measured thermal generation as a matched-supply offline reference.

The boundary is the electricity supplied by the seven thermal stations, not
whole-grid historical settlement. Wind/grid are replacement options only in
the optimization scenario, not fabricated historical measurements.
"""

from dataclasses import replace

import numpy as np
import pandas as pd

from src.dispatch_engine import station_grid_trade_shares
from src.period_accounting import period_metrics
from src.platform_config import STATION_CODES, load_runtime_units
from src.runtime_config import REPOSITORY_ROOT


def actual_baselines(cfg, histories, results):
    references = []
    for result in results:
        target = pd.Timestamp(result["time"])
        previous = target - pd.Timedelta(hours=cfg.dt_hour)
        current = {code: histories[code].loc[target] for code in STATION_CODES}
        initial = {code: histories[code].loc[previous] for code in STATION_CODES}
        power = np.array([float(current[c]["power"]) for c in STATION_CODES])
        measured = np.array([float(initial[c]["power"]) for c in STATION_CODES])
        if not np.isfinite(power).all() or (power < 0).any():
            raise ValueError("同期实际发电数据缺失或无效，不能生成运行基准")
        if not np.isclose(power.sum(), result["demand_mw"], atol=1e-5, rtol=0):
            raise ValueError("同期七站实测供电量与优化需求不一致，不能计算节省率")
        if not np.allclose(
            measured, [result["actual_mw"][c] for c in STATION_CODES], atol=1e-5, rtol=0
        ):
            raise ValueError("历史初值与保存的优化初值不一致")
        units = load_runtime_units(
            REPOSITORY_ROOT / "config/station_parameters.json", result["actual_mw"]
        )
        units = [replace(u, initial_on=int(initial[u.name]["running"])) for u in units]
        zero = np.zeros(1)
        solution = {
            "pgas": power[:, None],
            "unitOn": np.array([float(current[c]["running"]) for c in STATION_CODES])[:, None],
            # No wind/grid settlement is attributed to the measured thermal-only boundary.
            "pbuy": zero,
            "psell": zero,
            "preFarm": np.zeros((19, 1)),
            "pcurtFarm": np.zeros((19, 1)),
            "stationGridTradeShares": station_grid_trade_shares(measured[None, :]),
        }
        one = replace(cfg, t_points=1)
        metric = period_metrics(one, units, None, solution, np.zeros((19, 1)))[0]
        references.append(
            {
                "time": str(target),
                "thermal_mw": dict(zip(STATION_CODES, power.tolist(), strict=True)),
                "metrics": metric,
            }
        )
    return references
