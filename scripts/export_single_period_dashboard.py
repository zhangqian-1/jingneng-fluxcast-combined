"""Bundle the verified offline single-period study for identical, server-free sharing."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_single_period import read_history  # noqa: E402
from src.dispatch_engine import dispatch_config  # noqa: E402
from src.offline_actual_baseline import actual_baselines  # noqa: E402
from src.platform_config import (  # noqa: E402
    KNOWN_SOURCE_IDS,
    RENEWABLE_FARM_IDS,
    STATION_CODES,
    load_runtime_units,
)
from src.station_labels import STATION_NAMES  # noqa: E402


def build_data():
    source = json.loads(
        (ROOT / "output/single-period-study-20260923-single/results.json").read_text("utf-8")
    )
    results = source["single_period"]
    if len(results) != 96 or any(r["max_balance_error_mw"] > 1e-5 for r in results):
        raise ValueError("Expected 96 verified independent results")
    units = load_runtime_units(ROOT / "config/station_parameters.json", results[0]["actual_mw"])
    cfg = dispatch_config()
    references = actual_baselines(cfg, read_history(cfg), results)
    ids = {code: key for key, code in KNOWN_SOURCE_IDS.items()}
    farms = {
        f["farm_id"]: f
        for f in json.loads((ROOT / "config/renewable_capacities.json").read_text("utf-8"))["farms"]
    }
    rows = []
    periods = []
    for r, reference in zip(results, references, strict=True):
        if len(r["farm_accepted_mw"]) != 19:
            raise ValueError("Missing per-farm optimized results")
        row = {
            "time": r["time"],
            "equivalent_load_MW": r["demand_mw"],
            "gas_total_MW": sum(r["thermal_mw"].values()),
            "renewable_accepted_MW": r["renewable_accepted_mw"],
            "grid_buy_MW": r["grid_buy_mw"],
            "grid_sell_MW": 0.0,
            "curtailment_MW": r["step_metrics"]["curtailMWh"] * 4,
        }
        for code in STATION_CODES:
            row[f"{code}_MW"] = r["thermal_mw"][code]
            row[f"{code}_on"] = r["thermal_running"][code]
            row[f"baseline_{code}_MW"] = r["actual_mw"][code]
            row[f"same_period_actual_{code}_MW"] = reference["thermal_mw"][code]
        baseline = reference["metrics"]
        period = {
            **r["step_metrics"],
            "baselineCostYuan": baseline["objectiveYuan"],
            "baselineCarbonTon": baseline["carbonTon"],
            "baselineThermalMWh": baseline["thermalMWh"],
            **{f"baseline_{key}": value for key, value in baseline.items()},
        }
        row.update(
            {
                "actual_baseline_cost_yuan": baseline["objectiveYuan"],
                "optimized_cost_yuan": period["objectiveYuan"],
                "cost_saving_yuan": baseline["objectiveYuan"] - period["objectiveYuan"],
                "actual_baseline_carbon_ton": baseline["carbonTon"],
                "optimized_carbon_ton": period["carbonTon"],
                "carbon_reduction_ton": baseline["carbonTon"] - period["carbonTon"],
            }
        )
        periods.append(period)
        rows.append(row)
    return {
        "isSinglePeriod": True,
        "dataOrigin": "single_period_offline_study",
        "displayOnly": True,
        "snapshotId": "single-period-actual-comparison-20260923",
        "defaultIndex": 95,
        "summary": {**source["summary"], "solverMode": "highs"},
        "periodMinutes": 15,
        "comparison": {
            "status": "available",
            "basis": "same_period_measured_thermal_supply",
            "baselineLabel": "实际运行基准",
            "optimizedLabel": "优化方案",
            "note": "基准按同期七站实测发电核算；优化侧采用风光替代情景，非全网实测结算",
            "version": "2026-09-23",
        },
        "rows": rows,
        "periods": periods,
        "stations": [
            {**vars(u), "label": STATION_NAMES[u.name], "sourceId": ids[u.name]} for u in units
        ],
        "farms": [
            {
                **farms[farm],
                "forecast": [r["farm_available_mw"][i] for r in results],
                "accepted": [r["farm_accepted_mw"][i] for r in results],
            }
            for i, farm in enumerate(RENEWABLE_FARM_IDS)
        ],
    }


def main():
    data = build_data()
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    data_js = "window.SINGLE_PERIOD_DATA = " + encoded + ";\n"
    dashboard = ROOT / "dashboard"
    (dashboard / "single-period-data.js").write_text(data_js, encoding="utf-8")
    output = ROOT / "output/single-period-dashboard-share"
    output.mkdir(parents=True, exist_ok=True)
    page = (dashboard / "index.html").read_text("utf-8")
    page = page.replace(
        '<link rel="stylesheet" href="./styles.css" />',
        "<style>" + (dashboard / "styles.css").read_text("utf-8") + "</style>",
    )
    for asset in ("single-period-data.js", "app.js"):
        page = page.replace(
            f'<script src="./{asset}"></script>',
            "<script>"
            + (dashboard / asset).read_text("utf-8").replace("</script", "<\\/script")
            + "</script>",
        )
    (output / "七站单断面优化展示.html").write_text(page, encoding="utf-8")
    (output / "使用说明.txt").write_text(
        "将“七站单断面优化展示.html”发送到其他电脑，使用Chrome或Edge双击打开。\n"
        "页面、数据和交互均包含在一个文件内，不需要Python、服务或网络。\n"
        "上排显示累计、下排显示当前时段；拖动时间轴同步更新两排，可播放、查看单站及放大新能源。\n"
        "实际运行基准按同期七站实测功率核算；优化方案为相同供电量下的风光替代情景。\n"
        "这是固定的离线试算版本，不接收现场数据，也不自动更新；同一文件在各电脑数据一致。\n"
        "本文件不是公网网址；原网站尚未更新。\n",
        encoding="utf-8",
    )
    print(output / "七站单断面优化展示.html")


if __name__ == "__main__":
    main()
