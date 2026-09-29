from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from src.renewable_provider import FileRenewableProvider
from src.runtime_config import (
    input_directory,
    output_directory,
    positive_float_env,
)


@dataclass
class DispatchConfig:
    base_dir: Path
    data_dir: Path
    output_dir: Path
    renewable_dir: Path
    result_csv: Path
    summary_csv: Path
    result_json: Path
    t_points: int = 96
    dt_hour: float = 0.25
    load_day: str = "2025-06-05"
    renewable_day: str = "2026-09-19"
    grid_limit_ratio: float = 0.20
    curtail_cost_yuan_per_kwh: float = 0.60
    grid_emission_kg_per_kwh: float = 0.5554
    carbon_price_yuan_per_ton: float = 62.36
    natural_gas_kg_per_mj: float = 0.0561
    natural_gas_lhv_mj_per_nm3: float = 38.931
    mip_gap: float = 1e-4
    highs_time_limit_seconds: float = 300.0
    temperature_scenario_c: float = 30.0


@dataclass
class PlantParam:
    code: str
    keyword: str
    capacity_mw: float
    pmin_mw: float
    pmax_mw: float
    min_up_hour: float
    min_down_hour: float
    gen_cost_yuan_per_kwh: float
    ramp_mw_per_min: float
    max_start_per_day: int
    start_cost_yuan: float
    stop_cost_yuan: float
    gas_price_yuan_per_m3: float
    heat_rate_mj_per_kwh: float
    buy_price_yuan_per_kwh: float
    sell_price_yuan_per_kwh: float
    gas_emission_kg_per_kwh: float


@dataclass
class UnitParam:
    name: str
    plant_code: str
    point: str
    pmax: float
    pmin: float
    ramp_mw_per_min: float
    min_up_hour: float
    min_down_hour: float
    max_start_per_day: int
    gen_cost_yuan_per_kwh: float
    start_cost_yuan: float
    stop_cost_yuan: float
    gas_price_yuan_per_m3: float
    heat_rate_mj_per_kwh: float
    gas_emission_kg_per_kwh: float
    buy_price_yuan_per_kwh: float
    sell_price_yuan_per_kwh: float
    initial_mw: float
    initial_on: int


LOAD_POINTS: list[tuple[str, list[str]]] = [
    (
        "gard_240601_260101_15min.csv",
        ["GARD_11MBY0100000BJ01XQ01", "GARD_12MBY0100000BJ01XQ01", "GARD_13MKA01CE903BJ01XQ01"],
    ),
    ("jfrd_220101_260101_15min.csv", ["JFRD_11MKA01GA001BJ40XQ01"]),
    (
        "jqrd_220101_260101_15min.csv",
        ["JQRD_10CBA00FA107XQ93", "JQRD_10CBA00FA108XQ93", "JQRD_10CBA00FA109XQ93"],
    ),
    (
        "jxrd_240601_260101_15min.csv",
        [
            "JXRD_11MBY0100000BJ01XQ01",
            "JXRD_12MBY0100000BJ01XQ01",
            "JXRD_13MKA01GA001BJ02XQ01",
            "JXRD_15MKA01GA001BJ02XQ01",
            "JXRD_14MBY0100000BJ01XQ01",
        ],
    ),
    (
        "jyrd_230401_260401_15min.csv",
        ["JYRD_LOADCTL:GTMWSEL1_1.OUT", "JYRD_LOADCTL:GTMWSEL1_2.OUT", "JYRD_30DCS01:FU101.PNT"],
    ),
    ("szrd_220101_260101_15min.csv", ["SZRD_10DCS02FA133", "SZRD_10DCS02FA134"]),
    ("wlrd_220101_260101_15min.csv", ["WLRD_13MKA0100000BJ01XQ01", "WLRD_11MBY10CE901XQ01"]),
]

GAS_POINTS: list[tuple[str, str, list[str]]] = [
    (
        "GARD",
        "gard_240601_260101_15min.csv",
        ["GARD_11MBY0100000BJ01XQ01", "GARD_12MBY0100000BJ01XQ01", "GARD_13MKA01CE903BJ01XQ01"],
    ),
    ("JFRD", "jfrd_220101_260101_15min.csv", ["JFRD_11MKA01GA001BJ40XQ01"]),
    (
        "JQRD",
        "jqrd_220101_260101_15min.csv",
        ["JQRD_10CBA00FA107XQ93", "JQRD_10CBA00FA108XQ93", "JQRD_10CBA00FA109XQ93"],
    ),
    (
        "JXRD",
        "jxrd_240601_260101_15min.csv",
        [
            "JXRD_11MBY0100000BJ01XQ01",
            "JXRD_12MBY0100000BJ01XQ01",
            "JXRD_13MKA01GA001BJ02XQ01",
            "JXRD_15MKA01GA001BJ02XQ01",
            "JXRD_14MBY0100000BJ01XQ01",
        ],
    ),
    (
        "JYRD",
        "jyrd_230401_260401_15min.csv",
        ["JYRD_LOADCTL:GTMWSEL1_1.OUT", "JYRD_LOADCTL:GTMWSEL1_2.OUT", "JYRD_30DCS01:FU101.PNT"],
    ),
    ("SZRD", "szrd_220101_260101_15min.csv", ["SZRD_10DCS02FA133", "SZRD_10DCS02FA134"]),
    (
        "WLRD",
        "wlrd_220101_260101_15min.csv",
        ["WLRD_13MKA0100000BJ01XQ01", "WLRD_11MBY10CE901XQ01"],
    ),
]

# Authoritative mapping from the supplied appendix: JSON farmId -> station name.
RENEWABLE_FARM_TO_STATION: dict[int, str] = {
    1: "康保风电",
    2: "孟家房子光伏电站（一期）",
    3: "孟家房子光伏电站（二期）",
    4: "孟家房子光伏电站（三期）",
    7: "后杨庄光伏电站",
    8: "宁河光伏电站",
    10: "杨津庄风电场",
    11: "苗庄风电场",
    12: "板桥风电站",
    13: "郝家营风电场（二期）",
    16: "郝家营风电场（一期）",
    17: "大囫囵风电场（一期）",
    19: "大囫囵风电场（二期）",
    20: "官厅风电场",
    21: "麻黄峪风电站",
    22: "延庆光伏电站（一期）",
    23: "峻盛风电场",
    28: "东棘坨风电场",
    29: "延庆光伏电站（二期）",
}

# Names used by the capacity workbook.  The two source files use different naming
# conventions; farm 23 is recorded as "宁河峡盛风电场" in the capacity workbook.
RENEWABLE_FARM_TO_CAPACITY_STATION: dict[int, str] = {
    1: "康保风电场",
    2: "孟家房子一站",
    3: "孟家房子二站",
    4: "孟家房子三站",
    7: "后杨庄光伏电站",
    8: "宁河光伏电站",
    10: "杨津庄风电场",
    11: "苗庄风电场",
    12: "板桥风电场",
    13: "郝家营风电场二期",
    16: "郝家营风电场一期",
    17: "大囫囵风电场一期",
    19: "大囫囵风电场二期",
    20: "官厅风电场",
    21: "麻黄峪风电场",
    22: "延庆光伏电站（一期）",
    23: "宁河峡盛风电场",
    28: "东棘坨风电场",
    29: "延庆光伏电站（二期）",
}
RENEWABLE_CAPACITY_WORKBOOK = "京津冀场站现有功率预测系统数量统计-含测点.xlsx"

PARAMETER_WORKBOOK = "智慧调度数据需求清单汇总.xlsx"
PARAMETER_SHEET = "参数需求汇总"
TABLE_NAME_TO_CODE = {
    "高安屯热电": "GARD",
    "京丰燃气": "JFRD",
    "京桥热电": "JQRD",
    "京西热电": "JXRD",
    "京阳热电": "JYRD",
    "上庄热电": "SZRD",
    "未来热电": "WLRD",
}
# The workbook refers to an absent ambient-temperature/load curve for JYRD.
# The user approved this 30°C non-heating-period engineering assumption.
JYRD_NORMAL_TEMPERATURE_C = 30.0
JYRD_NORMAL_LIMIT_MW = (240.0, 348.0)
NON_HEATING_MONTHS = (5, 6, 7, 8, 9)
EMPIRICAL_UPPER_QUANTILE = 0.995
PMIN_INCONSISTENCY_RATE = 0.03
USER_FORCED_STATION_PMIN_MW = {"JYRD": 240.0, "WLRD": 128.0}
THERMAL_MODEL_METADATA = {
    "granularity": "station_aggregate",
    "pmaxRule": "min(installed_capacity, max(parameter_pmax, non_heating_online_p99_5))",
    "pminRule": "parameter_pmin when online-history inconsistency is <= 3%; otherwise 0 MW unless user-forced",
    "initialStateRule": "latest measurement before the dispatch day; pre-horizon online state is not a start",
    "dailyTransitionLimit": "at most one in-horizon start and one in-horizon stop per station",
    "transitionRampRule": "normal interval ramp while online; max(normal interval ramp, pmin) on start/stop",
    "userForcedPminMW": USER_FORCED_STATION_PMIN_MW,
    "nonHeatingMonths": list(NON_HEATING_MONTHS),
    "onlineUpperQuantile": EMPIRICAL_UPPER_QUANTILE,
}


def dispatch_config(
    base_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> DispatchConfig:
    root = Path(base_dir) if base_dir else input_directory()
    result_dir = Path(output_dir) if output_dir else output_directory()
    renewable_dir = root / "新能源场站预测输入数据"
    highs_time_limit_seconds = positive_float_env("HIGHS_TIME_LIMIT_SECONDS", 300)
    return DispatchConfig(
        base_dir=root,
        data_dir=root / "电机系参数需求",
        output_dir=result_dir,
        renewable_dir=renewable_dir,
        renewable_day=os.getenv("RENEWABLE_FORECAST_DAY", "2026-09-19"),
        result_csv=result_dir / "智慧调度Python调度明细.csv",
        summary_csv=result_dir / "智慧调度Python汇总指标.csv",
        result_json=result_dir / "智慧调度Python完整结果.json",
        highs_time_limit_seconds=highs_time_limit_seconds,
    )


def read_table_output_limits(
    base_dir: Path, temperature_c: float
) -> dict[str, tuple[float, float]]:
    """Read station-level Pmin/Pmax values from the supplied parameter workbook."""
    parameter_path = base_dir / PARAMETER_WORKBOOK
    if not parameter_path.exists():
        raise FileNotFoundError(f"Parameter workbook not found: {parameter_path}")

    table = pd.read_excel(parameter_path, sheet_name=PARAMETER_SHEET)
    limits: dict[str, tuple[float, float]] = {}
    for table_name, code in TABLE_NAME_TO_CODE.items():
        row = table.loc[
            (table["对象/电厂"] == table_name) & (table["参数名"] == "燃气轮机输出功率上下限约束")
        ]
        if row.empty:
            raise ValueError(f"Missing output-limit row for {table_name}")
        value = str(row.iloc[0]["参数值"])
        numbers = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", value.splitlines()[0])]
        if code == "JYRD":
            if not np.isclose(temperature_c, JYRD_NORMAL_TEMPERATURE_C):
                raise ValueError(
                    f"JYRD has no temperature/load curve in the workbook; only the approved "
                    f"{JYRD_NORMAL_TEMPERATURE_C:.0f}°C assumption is available."
                )
            limits[code] = JYRD_NORMAL_LIMIT_MW
        elif len(numbers) >= 2:
            limits[code] = (min(numbers[:2]), max(numbers[:2]))
        else:
            raise ValueError(f"Cannot parse Pmin/Pmax for {table_name}: {value}")

    missing = set(TABLE_NAME_TO_CODE.values()) - set(limits)
    if missing:
        raise ValueError(f"Missing output limits for: {sorted(missing)}")
    return limits


def daily_transition_limits(unit: UnitParam) -> tuple[int, int]:
    """Return in-horizon start/stop limits without charging the pre-horizon state.

    ``initial_on`` describes the state immediately before the first dispatch
    interval.  It is not itself an off-to-on transition during the dispatch day,
    so an initially online station retains its permitted restart after one stop.
    """
    return max(0, int(unit.max_start_per_day)), 1


def interval_ramp_limits_mw(unit: UnitParam, dt_min: float) -> tuple[float, float, float]:
    """Return normal, startup, and shutdown MW allowances for one interval.

    The source workbook supplies only the normal MW/min ramp and the online Pmin,
    not separate synchronized startup/shutdown ramps.  A transition interval must
    at least be able to reach or leave Pmin; normal online intervals still use the
    stated MW/min limit.  This is material for JFRD, where 13 MW/min × 15 min is
    195 MW but the online minimum is 205 MW.
    """
    normal = max(0.0, float(unit.ramp_mw_per_min) * float(dt_min))
    transition = max(normal, float(unit.pmin))
    return normal, transition, transition


def calibrate_station_output_limits(
    cfg: DispatchConfig,
    plants: list[PlantParam],
    table_limits: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Calibrate seven station-level limits from non-heating-period aggregate measurements."""
    plant_map = {plant.code: plant for plant in plants}
    calibrated: dict[str, tuple[float, float]] = {}
    for code, file_name, points in GAS_POINTS:
        data = pd.read_csv(cfg.data_dir / file_name, usecols=["ts", *points])
        timestamps = pd.to_datetime(data["ts"])
        total_mw = (
            data.loc[timestamps.dt.month.isin(NON_HEATING_MONTHS), points].clip(lower=0).sum(axis=1)
        )
        if total_mw.empty:
            raise ValueError(f"No non-heating-period measurements found for {code}")

        table_pmin, table_pmax = table_limits[code]
        observed_peak = float(total_mw.max())
        on_threshold = max(5.0, 0.05 * observed_peak)
        online = total_mw.loc[total_mw > on_threshold]
        if online.empty:
            raise ValueError(f"No online non-heating-period measurements found for {code}")
        empirical_pmax = float(np.quantile(online.to_numpy(dtype=float), EMPIRICAL_UPPER_QUANTILE))
        pmax = min(plant_map[code].capacity_mw, max(table_pmax, empirical_pmax))
        pmin_inconsistency = float((online < table_pmin - 1e-6).mean()) if not online.empty else 1.0
        if code in USER_FORCED_STATION_PMIN_MW:
            pmin = USER_FORCED_STATION_PMIN_MW[code]
        else:
            pmin = table_pmin if pmin_inconsistency <= PMIN_INCONSISTENCY_RATE else 0.0
        calibrated[code] = (pmin, pmax)
    return calibrated


def read_plant_parameters(cfg: DispatchConfig) -> list[PlantParam]:
    table_limits = read_table_output_limits(cfg.base_dir, cfg.temperature_scenario_c)
    raw = [
        ("GARD", "高安屯", 845, 125, 260, 6, 2, 0.48, 70, 3, 300000, 0, 2.64, 5.4, 0.615, 0.614),
        (
            "JFRD",
            "京丰",
            410,
            205,
            410,
            4,
            0.5,
            0.5856,
            13,
            1,
            310000,
            25500,
            2.35,
            6.38,
            0.614,
            0.675,
        ),
        ("JQRD", "京桥", 838, 20, 298, 5, 1, 0.635, 50, 1, 288000, 13000, 2.50, 7.2006, 0.61, 0.63),
        (
            "JXRD",
            "京西",
            1307.95,
            125,
            300,
            5,
            1,
            0.5223,
            40,
            4,
            89900,
            26600,
            2.28,
            5.59,
            0.5354,
            0.5508,
        ),
        (
            "JYRD",
            "京阳",
            783.48,
            240,
            348,
            2,
            1,
            0.5279,
            30,
            1,
            158100,
            34600,
            2.49,
            5.019,
            0.5289,
            0.5540,
        ),
        ("SZRD", "上庄", 266, 78, 182, 5, 1.5, 0.70, 11, 1, 195500, 35200, 2.49, 7.48, 0.61, 0.67),
        ("WLRD", "未来", 255, 128, 255, 3, 1, 0.63, 11, 1, 120000, 0, 2.508, 8.043, 0.60, 0.65),
    ]
    plants = []
    for row in raw:
        gas_emission = row[13] * cfg.natural_gas_kg_per_mj
        plant = PlantParam(*row, gas_emission_kg_per_kwh=gas_emission)
        plants.append(plant)

    calibrated_limits = calibrate_station_output_limits(cfg, plants, table_limits)
    return [
        replace(
            plant,
            pmin_mw=calibrated_limits[plant.code][0],
            pmax_mw=calibrated_limits[plant.code][1],
            max_start_per_day=1,
        )
        for plant in plants
    ]


def read_day_points(file_path: Path, points: list[str], day: str) -> pd.DataFrame:
    data = pd.read_csv(file_path)
    ts = pd.to_datetime(data["ts"])
    selected = data.loc[ts.dt.strftime("%Y-%m-%d") == day, points]
    return selected.iloc[:96].reset_index(drop=True)


def read_pre_horizon_points(file_path: Path, points: list[str], day: str) -> pd.Series:
    """Read the latest measurement before the dispatch day starts."""
    data = pd.read_csv(file_path)
    ts = pd.to_datetime(data["ts"])
    horizon_start = pd.Timestamp(day)
    candidates = ts.loc[ts < horizon_start]
    if candidates.empty:
        raise ValueError(f"No pre-horizon measurement before {day} in {file_path}")
    previous_index = candidates.idxmax()
    return data.loc[previous_index, points]


def read_renewable_capacity_limits(cfg: DispatchConfig) -> dict[int, float]:
    """Return installed MW limits keyed by the appendix farmId mapping."""
    candidates = [
        cfg.base_dir.parent / RENEWABLE_CAPACITY_WORKBOOK,
        cfg.base_dir / RENEWABLE_CAPACITY_WORKBOOK,
    ]
    capacity_path = next((path for path in candidates if path.exists()), None)
    if capacity_path is None:
        raise FileNotFoundError(
            f"Renewable capacity workbook not found; checked: {', '.join(map(str, candidates))}"
        )

    table = pd.read_excel(capacity_path)
    if table.shape[1] < 5:
        raise ValueError(f"Renewable capacity workbook has unexpected layout: {capacity_path}")
    station_names = table.iloc[:, 1].astype(str).str.strip()
    capacities = pd.to_numeric(table.iloc[:, 4], errors="coerce")

    limits: dict[int, float] = {}
    for farm_id, station_name in RENEWABLE_FARM_TO_CAPACITY_STATION.items():
        matched = capacities.loc[(station_names == station_name) & capacities.notna()]
        if len(matched) != 1:
            raise ValueError(
                f"Expected exactly one capacity record for farmId={farm_id}, "
                f"station={station_name!r}; found {len(matched)}"
            )
        if float(matched.iloc[0]) <= 0:
            raise ValueError(f"Installed capacity must be positive for farmId={farm_id}")
        limits[farm_id] = float(matched.iloc[0])
    return limits


def validate_renewable_forecast_matrix(
    farm_ids: list[int],
    farm_forecast_mw: np.ndarray,
    capacity_limits_mw: dict[int, float],
    t_points: int,
) -> None:
    """Reject incomplete, invalid, or capacity-exceeding renewable inputs."""
    expected_ids = set(RENEWABLE_FARM_TO_STATION)
    supplied_ids = set(farm_ids)
    if len(farm_ids) != len(supplied_ids):
        raise ValueError("Duplicate renewable farmId values found")
    if supplied_ids != expected_ids:
        raise ValueError(
            f"Renewable farmId set does not match the appendix mapping; "
            f"missing={sorted(expected_ids - supplied_ids)}, unexpected={sorted(supplied_ids - expected_ids)}"
        )
    if farm_forecast_mw.shape != (len(farm_ids), t_points):
        raise ValueError(
            f"Renewable forecast matrix shape must be ({len(farm_ids)}, {t_points}), "
            f"got {farm_forecast_mw.shape}"
        )
    if not np.isfinite(farm_forecast_mw).all():
        raise ValueError("Renewable forecast contains non-finite values")
    if (farm_forecast_mw < 0).any():
        raise ValueError("Renewable forecast contains negative power")

    for index, farm_id in enumerate(farm_ids):
        if farm_id not in capacity_limits_mw:
            raise ValueError(f"No installed-capacity limit found for farmId={farm_id}")
        violation = np.flatnonzero(farm_forecast_mw[index] > capacity_limits_mw[farm_id] + 1e-6)
        if violation.size:
            t = int(violation[0])
            raise ValueError(
                f"Renewable forecast exceeds installed capacity: farmId={farm_id}, "
                f"station={RENEWABLE_FARM_TO_STATION[farm_id]}, timeIndex={t}, "
                f"forecast={farm_forecast_mw[index, t]:.3f} MW, "
                f"capacity={capacity_limits_mw[farm_id]:.3f} MW"
            )


def read_dispatch_measurements(
    cfg: DispatchConfig, plants: list[PlantParam]
) -> tuple[np.ndarray, np.ndarray, list[UnitParam]]:
    demand_mw = np.zeros(cfg.t_points)
    for file_name, points in LOAD_POINTS:
        day_data = read_day_points(cfg.data_dir / file_name, points, cfg.load_day)
        demand_mw += day_data.clip(lower=0).sum(axis=1).to_numpy()

    plant_map = {p.code: p for p in plants}
    units: list[UnitParam] = []
    base_gas_cols: list[np.ndarray] = []
    for code, file_name, points in GAS_POINTS:
        plant = plant_map[code]
        source_path = cfg.data_dir / file_name
        day_data = read_day_points(source_path, points, cfg.load_day)
        pre_horizon_data = read_pre_horizon_points(source_path, points, cfg.load_day)
        measured_total = day_data.clip(lower=0).sum(axis=1).to_numpy(dtype=float)
        pre_horizon_total = float(
            pd.to_numeric(pre_horizon_data, errors="coerce").clip(lower=0).sum()
        )
        initial_on = int(pre_horizon_total > 1.0)
        initial_mw = (
            float(np.clip(pre_horizon_total, plant.pmin_mw, plant.pmax_mw)) if initial_on else 0.0
        )
        # Preserve the historical baseline exactly as measured.  Pmin/Pmax apply
        # only to the optimized dispatch decision, never to the baseline curve.
        base_profile = measured_total.copy()
        units.append(
            UnitParam(
                name=code,
                plant_code=code,
                point="|".join(points),
                pmax=plant.pmax_mw,
                pmin=plant.pmin_mw,
                ramp_mw_per_min=max(0.1, plant.ramp_mw_per_min),
                min_up_hour=max(cfg.dt_hour, plant.min_up_hour),
                min_down_hour=max(cfg.dt_hour, plant.min_down_hour),
                max_start_per_day=1,
                gen_cost_yuan_per_kwh=plant.gen_cost_yuan_per_kwh,
                start_cost_yuan=plant.start_cost_yuan,
                stop_cost_yuan=plant.stop_cost_yuan,
                gas_price_yuan_per_m3=plant.gas_price_yuan_per_m3,
                heat_rate_mj_per_kwh=plant.heat_rate_mj_per_kwh,
                gas_emission_kg_per_kwh=plant.gas_emission_kg_per_kwh,
                buy_price_yuan_per_kwh=plant.buy_price_yuan_per_kwh,
                sell_price_yuan_per_kwh=plant.sell_price_yuan_per_kwh,
                initial_mw=initial_mw,
                initial_on=initial_on,
            )
        )
        base_gas_cols.append(base_profile)
    return demand_mw, np.column_stack(base_gas_cols), units


def read_renewable_forecast(cfg: DispatchConfig) -> tuple[np.ndarray, np.ndarray, list[int]]:
    axis = pd.date_range(cfg.renewable_day, periods=cfg.t_points, freq="15min", tz="Asia/Shanghai")
    normalized = tuple(axis.tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S"))
    forecast = FileRenewableProvider(cfg.renewable_dir, read_renewable_capacity_limits(cfg)).load(
        normalized
    )
    return forecast.values_mw.sum(axis=0), forecast.values_mw, list(forecast.farm_ids)


def station_marginal_cost_yuan_per_kwh(unit: UnitParam, lhv_mj_per_nm3: float) -> float:
    """Return the table's fuel-inclusive generation cost; gas is reference-only."""
    if lhv_mj_per_nm3 <= 0:
        raise ValueError("Natural-gas lower heating value must be positive")
    return float(unit.gen_cost_yuan_per_kwh)


def station_grid_trade_shares(station_load_mw: np.ndarray) -> np.ndarray:
    """Allocate aggregate grid exchange by each station's share of aggregate load.

    Input shape is (time, station); output shape is (station, time).  This keeps
    the seven-station aggregate power balance while preventing price arbitrage
    between station accounts.  A zero-load interval is split equally.
    """
    loads = np.asarray(station_load_mw, dtype=float)
    if loads.ndim != 2 or loads.shape[1] == 0:
        raise ValueError("Station load matrix must have shape (time, station)")
    if not np.isfinite(loads).all() or (loads < 0).any():
        raise ValueError("Station load matrix must contain finite non-negative values")

    totals = loads.sum(axis=1)
    shares_by_time = np.full_like(loads, 1.0 / loads.shape[1], dtype=float)
    positive = totals > np.finfo(float).eps
    shares_by_time[positive] = loads[positive] / totals[positive, None]
    return shares_by_time.T


def station_grid_cost_yuan(
    buy_mw: np.ndarray,
    sell_mw: np.ndarray,
    station_shares: np.ndarray,
    units: list[UnitParam],
    dt_hour: float,
) -> float:
    """Settle aggregate grid exchange using every station's fixed tariff."""
    buy = np.asarray(buy_mw, dtype=float)
    sell = np.asarray(sell_mw, dtype=float)
    shares = np.asarray(station_shares, dtype=float)
    if buy.shape != sell.shape or buy.ndim != 1:
        raise ValueError("Grid buy and sell arrays must be one-dimensional with equal shape")
    if shares.shape != (len(units), buy.size):
        raise ValueError(
            f"Station share matrix must have shape ({len(units)}, {buy.size}), got {shares.shape}"
        )
    buy_prices = np.array([unit.buy_price_yuan_per_kwh for unit in units])[:, None]
    sell_prices = np.array([unit.sell_price_yuan_per_kwh for unit in units])[:, None]
    allocated_buy = shares * buy[None, :]
    allocated_sell = shares * sell[None, :]
    return float(
        ((buy_prices * allocated_buy - sell_prices * allocated_sell) * 1000).sum() * dt_hour
    )
