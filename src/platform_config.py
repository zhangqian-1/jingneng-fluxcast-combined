"""Static platform contract and validated runtime configuration."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class PlatformConfigurationError(ValueError):
    """Raised when deployment configuration does not satisfy the platform contract."""


STATION_CODES = ("GARD", "JFRD", "JQRD", "JXRD", "JYRD", "SZRD", "WLRD")

# 多厂信息表_v2: only the seven stations covered by this dispatch model.
KNOWN_SOURCE_IDS = {2: "JYRD", 3: "JQRD", 4: "JFRD", 5: "GARD", 6: "JXRD", 7: "WLRD", 8: "SZRD"}

# Measurement-point names and station ownership follow the document's explicit table.
STATION_MEASUREMENT_POINTS: dict[str, tuple[str, ...]] = {
    "GARD": (
        "GARD_11MBY0100000BJ01XQ01",
        "GARD_12MBY0100000BJ01XQ01",
        "GARD_13MKA01CE903BJ01XQ01",
    ),
    "JFRD": ("JFRD_11MKA01GA001BJ40XQ01",),
    "JQRD": (
        "JQRD_10CBA00FA107XQ93",
        "JQRD_10CBA00FA108XQ93",
        "JQRD_10CBA00FA109XQ93",
    ),
    "JXRD": (
        "JXRD_11MBY0100000BJ01XQ01",
        "JXRD_12MBY0100000BJ01XQ01",
        "JXRD_13MKA01GA001BJ02XQ01",
        "JXRD_15MKA01GA001BJ02XQ01",
        "JXRD_14MBY0100000BJ01XQ01",
    ),
    "JYRD": (
        "JYRD_LOADCTL:GTMWSEL1_1.OUT",
        "JYRD_LOADCTL:GTMWSEL1_2.OUT",
        "JYRD_30DCS01:FU101.PNT",
    ),
    "SZRD": ("SZRD_10DCS02FA133", "SZRD_10DCS02FA134"),
    "WLRD": ("WLRD_13MKA0100000BJ01XQ01", "WLRD_11MBY10CE901XQ01"),
}

RENEWABLE_FARM_IDS = (1, 2, 3, 4, 7, 8, 10, 11, 12, 13, 16, 17, 19, 20, 21, 22, 23, 28, 29)


def platform_point_name(raw: str) -> str:
    """Apply the platform's documented measurement-name escaping rule."""

    return raw.replace(".", "_")


def required_platform_points(station: str) -> tuple[str, ...]:
    """Return the escaped required input keys for one station."""

    try:
        return tuple(platform_point_name(point) for point in STATION_MEASUREMENT_POINTS[station])
    except KeyError as exc:
        raise PlatformConfigurationError(f"未知场站代码: {station}") from exc


def _read_json_object(path: str | Path, label: str) -> dict[str, Any]:
    selected = Path(path)
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlatformConfigurationError(f"{label}不存在: {selected}") from exc
    except json.JSONDecodeError as exc:
        raise PlatformConfigurationError(f"{label}不是有效JSON") from exc
    if not isinstance(payload, dict):
        raise PlatformConfigurationError(f"{label}根节点必须是JSON对象")
    return payload


def _finite_float(record: Mapping[str, Any], key: str, context: str) -> float:
    try:
        value = float(record[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PlatformConfigurationError(f"{context}缺少有效数值字段{key}") from exc
    if not math.isfinite(value):
        raise PlatformConfigurationError(f"{context}字段{key}必须为有限数值")
    return value


def load_runtime_units(path: str | Path, initial_mw: Mapping[str, float]):
    """Build the existing dispatch-engine UnitParam objects from versioned JSON."""

    from src.dispatch_engine import UnitParam

    payload = _read_json_object(path, "场站参数配置")
    records = payload.get("stations")
    if not isinstance(records, list):
        raise PlatformConfigurationError("场站参数配置缺少stations列表")
    by_code: dict[str, Mapping[str, Any]] = {}
    for item in records:
        if not isinstance(item, Mapping):
            raise PlatformConfigurationError("stations中的每一项必须是JSON对象")
        code = str(item.get("code", "")).strip().upper()
        if not code or code in by_code:
            raise PlatformConfigurationError(f"场站参数code为空或重复: {code!r}")
        by_code[code] = item
    missing = sorted(set(STATION_CODES) - set(by_code))
    unexpected = sorted(set(by_code) - set(STATION_CODES))
    if missing or unexpected:
        raise PlatformConfigurationError(
            f"场站参数必须覆盖七站，缺少: {missing}，未知: {unexpected}"
        )
    missing_initial = sorted(set(STATION_CODES) - set(initial_mw))
    if missing_initial:
        raise PlatformConfigurationError(f"实时初始出力缺少场站: {missing_initial}")

    units = []
    for code in STATION_CODES:
        item = by_code[code]
        points = item.get("measurement_points")
        if not isinstance(points, list) or not all(isinstance(point, str) for point in points):
            raise PlatformConfigurationError(f"场站{code}缺少measurement_points列表")
        expected_points = list(STATION_MEASUREMENT_POINTS[code])
        if points != expected_points:
            raise PlatformConfigurationError(f"场站{code}测点与正式清单不一致")
        pmin = _finite_float(item, "pmin", code)
        pmax = _finite_float(item, "pmax", code)
        if pmin < 0 or pmax <= 0 or pmin > pmax:
            raise PlatformConfigurationError(f"场站{code}出力上下限无效: Pmin={pmin}, Pmax={pmax}")
        raw_initial = float(initial_mw[code])
        if not math.isfinite(raw_initial) or raw_initial < 0:
            raise PlatformConfigurationError(f"场站{code}实时初始出力必须为非负有限数值")
        initial_on = int(raw_initial > 1.0)
        initial = float(min(max(raw_initial, pmin), pmax)) if initial_on else 0.0
        max_start = int(_finite_float(item, "max_start_per_day", code))
        if max_start != 1:
            raise PlatformConfigurationError(f"场站{code}每日最大启动次数必须为1")
        units.append(
            UnitParam(
                name=code,
                plant_code=code,
                point="|".join(points),
                pmax=pmax,
                pmin=pmin,
                ramp_mw_per_min=_finite_float(item, "ramp_mw_per_min", code),
                min_up_hour=_finite_float(item, "min_up_hour", code),
                min_down_hour=_finite_float(item, "min_down_hour", code),
                max_start_per_day=max_start,
                gen_cost_yuan_per_kwh=_finite_float(item, "gen_cost_yuan_per_kwh", code),
                start_cost_yuan=_finite_float(item, "start_cost_yuan", code),
                stop_cost_yuan=_finite_float(item, "stop_cost_yuan", code),
                gas_price_yuan_per_m3=_finite_float(item, "gas_price_yuan_per_m3", code),
                heat_rate_mj_per_kwh=_finite_float(item, "heat_rate_mj_per_kwh", code),
                gas_emission_kg_per_kwh=_finite_float(item, "gas_emission_kg_per_kwh", code),
                buy_price_yuan_per_kwh=_finite_float(item, "buy_price_yuan_per_kwh", code),
                sell_price_yuan_per_kwh=_finite_float(item, "sell_price_yuan_per_kwh", code),
                initial_mw=initial,
                initial_on=initial_on,
            )
        )
    return units


def load_renewable_capacities(path: str | Path) -> dict[int, float]:
    """Load and validate all nineteen documented renewable capacity limits."""

    payload = _read_json_object(path, "新能源容量配置")
    records = payload.get("farms")
    if not isinstance(records, list):
        raise PlatformConfigurationError("新能源容量配置缺少farms列表")
    capacities: dict[int, float] = {}
    for item in records:
        if not isinstance(item, Mapping):
            raise PlatformConfigurationError("farms中的每一项必须是JSON对象")
        try:
            farm_id = int(item["farm_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PlatformConfigurationError("新能源容量记录缺少有效farm_id") from exc
        if farm_id in capacities:
            raise PlatformConfigurationError(f"新能源容量farm_id重复: {farm_id}")
        capacity = _finite_float(item, "capacity_mw", f"farmId={farm_id}")
        if capacity <= 0:
            raise PlatformConfigurationError(f"farmId={farm_id}装机容量必须大于0")
        capacities[farm_id] = capacity
    missing = sorted(set(RENEWABLE_FARM_IDS) - set(capacities))
    unexpected = sorted(set(capacities) - set(RENEWABLE_FARM_IDS))
    if missing or unexpected:
        raise PlatformConfigurationError(
            f"新能源容量必须覆盖19站，缺少: {missing}，未知: {unexpected}"
        )
    return {farm_id: capacities[farm_id] for farm_id in RENEWABLE_FARM_IDS}
