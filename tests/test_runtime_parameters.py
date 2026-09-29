from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.platform_config import (
    RENEWABLE_FARM_IDS,
    STATION_CODES,
    PlatformConfigurationError,
    load_renewable_capacities,
    load_runtime_units,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_runtime_station_parameters_build_seven_unit_params() -> None:
    units = load_runtime_units(
        CONFIG_DIR / "station_parameters.json",
        initial_mw={code: 0.0 for code in STATION_CODES},
    )

    assert [unit.name for unit in units] == list(STATION_CODES)
    assert next(unit for unit in units if unit.name == "JYRD").pmin == 240.0
    assert next(unit for unit in units if unit.name == "WLRD").pmin == 128.0
    assert all(unit.max_start_per_day == 1 for unit in units)


def test_runtime_initial_state_is_clipped_to_documented_station_limits() -> None:
    initial = {code: 0.0 for code in STATION_CODES}
    initial["JYRD"] = 1.01
    initial["GARD"] = 100_000.0

    units = load_runtime_units(CONFIG_DIR / "station_parameters.json", initial_mw=initial)

    assert next(unit for unit in units if unit.name == "JYRD").initial_mw == 240.0
    gard = next(unit for unit in units if unit.name == "GARD")
    assert gard.initial_mw == gard.pmax
    assert gard.initial_on == 1


def test_runtime_capacity_config_covers_authoritative_farm_ids() -> None:
    capacities = load_renewable_capacities(CONFIG_DIR / "renewable_capacities.json")

    assert tuple(capacities) == RENEWABLE_FARM_IDS
    assert all(value > 0 for value in capacities.values())


def test_runtime_capacity_loader_rejects_missing_farm(tmp_path) -> None:
    source = json.loads((CONFIG_DIR / "renewable_capacities.json").read_text(encoding="utf-8"))
    source["farms"].pop()
    path = tmp_path / "capacities.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(PlatformConfigurationError, match="缺少"):
        load_renewable_capacities(path)
