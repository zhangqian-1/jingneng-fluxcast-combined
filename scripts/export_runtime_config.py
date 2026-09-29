"""Export validated offline station parameters and renewable capacities to JSON."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.dispatch_engine import (  # noqa: E402
    RENEWABLE_FARM_TO_STATION,
    dispatch_config,
    read_dispatch_measurements,
    read_plant_parameters,
    read_renewable_capacity_limits,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def export_runtime_config(input_dir: Path, output_dir: Path) -> None:
    cfg = dispatch_config(input_dir)
    plants = read_plant_parameters(cfg)
    _, _, units = read_dispatch_measurements(cfg, plants)
    capacities = read_renewable_capacity_limits(cfg)

    station_records = []
    for unit in units:
        record = asdict(unit)
        record["code"] = unit.name
        record["measurement_points"] = unit.point.split("|")
        for runtime_only in ("name", "plant_code", "point", "initial_mw", "initial_on"):
            record.pop(runtime_only)
        station_records.append(record)
    _write_json(
        output_dir / "station_parameters.json",
        {
            "schema_version": 1,
            "source": "validated offline package",
            "stations": station_records,
        },
    )

    farm_records = [
        {
            "farm_id": farm_id,
            "station_name": RENEWABLE_FARM_TO_STATION[farm_id],
            "capacity_mw": capacities[farm_id],
        }
        for farm_id in capacities
    ]
    _write_json(
        output_dir / "renewable_capacities.json",
        {
            "schema_version": 1,
            "source": "京津冀场站现有功率预测系统数量统计-含测点.xlsx",
            "farms": farm_records,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="导出平台实时运行所需的版本化静态配置")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=REPOSITORY_ROOT / "config")
    args = parser.parse_args()
    export_runtime_config(args.input_dir.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
