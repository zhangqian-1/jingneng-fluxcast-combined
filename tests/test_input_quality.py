from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.renewable_provider import (
    InlineRenewableProvider,
    LongTableRenewableProvider,
    RenewableInputError,
    read_forecast_files,
)
from tests.test_forecast_integration import DIRECTORY, axis
from tests.test_renewable_provider import capacities, normalized_axis, renewable_frames


def logs():
    return [
        json.loads(line)
        for line in Path(os.environ["WORK_LOG_PATH"]).read_text(encoding="utf-8").splitlines()
    ]


def test_capacity_fault_carries_same_farm_and_is_idempotent():
    frames = renewable_frames()
    frames[3]["farm_1_predictedPower"] = 1000.0
    provider = InlineRenewableProvider(capacities())
    a = provider.load(frames, normalized_axis())
    b = provider.load(frames, normalized_axis())
    assert a.values_mw[0, 3] == a.values_mw[0, 2]
    assert a.values_mw[1, 3] == capacities()[2] / 2
    assert a.payload_hash == b.payload_hash
    assert logs()[0]["original_value"] == 1000.0
    frames[3]["farm_1_predictedPower"] = capacities()[1] / 2
    assert provider.load(frames, normalized_axis()).payload_hash != a.payload_hash


def test_first_forecast_fault_can_use_exact_previous_interval_in_same_batch():
    rows = read_forecast_files(DIRECTORY)
    expected = rows[95]["predictedPower"]
    rows.pop(96)
    result = LongTableRenewableProvider(capacities()).load(rows, axis())
    assert result.values_mw[0, 0] == expected
    assert result.adjustments[0]["source_timestamp"] == "2026-09-19 15:45:00+00:00"


def test_missing_entire_farm_is_not_borrowed_from_another_farm():
    rows = [r for r in read_forecast_files(DIRECTORY) if r["farmId"] != 1]
    with pytest.raises(RenewableInputError, match="无可用的上一时刻"):
        LongTableRenewableProvider(capacities()).load(rows, axis())
