from __future__ import annotations

import csv
import re
from pathlib import Path

from scripts.check_delivery import check_input_data, missing_arm_wheels

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_measurement_document_contains_every_explicit_source_row() -> None:
    with (DOCS / "measurement-points.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 38
    assert len({row["platform_key"] for row in rows}) == 38
    assert sum(row["category"] == "thermal" for row in rows) == 19
    assert sum(row["category"] == "renewable" for row in rows) == 19
    assert all(row["unit"] == "MW" for row in rows)
    assert all(row["sampling_minutes"] == "15" for row in rows)
    assert all(row["required"] == "true" for row in rows)
    expected_ids = {
        "JYRD": "2",
        "JQRD": "3",
        "JFRD": "4",
        "GARD": "5",
        "JXRD": "6",
        "WLRD": "7",
        "SZRD": "8",
    }
    for row in rows:
        if row["category"] == "thermal":
            assert row["source_id"] == expected_ids[row["source_station"]]
            assert row["farm_id"] == ""
        else:
            assert row["source_id"] == ""


def test_lock_contains_required_arm_wheels_for_supported_python() -> None:
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")

    assert missing_arm_wheels(text) == []


def test_arm_checker_reports_missing_required_wheel() -> None:
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    damaged = re.sub(r'scipy-[^"\s]*cp310[^"\s]*aarch64[^"\s]*\.whl', "scipy-missing-arm.whl", text)

    assert "scipy cp310" in missing_arm_wheels(damaged)


def test_packaged_inputs_are_complete_and_match_original_hashes():
    result = check_input_data()
    assert result["files"] == 28
    assert result["bytes"] == 66046581
