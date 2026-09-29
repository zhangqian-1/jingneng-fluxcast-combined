"""Regression coverage for the delivered 202609180800 upstream forecast batch."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.dispatch_engine import dispatch_config, read_renewable_forecast
from src.platform_config import load_renewable_capacities
from src.renewable_provider import (
    LongTableRenewableProvider,
    RenewableInputError,
    read_forecast_files,
)

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data" / "新能源场站预测输入数据"


def axis(day="2026-09-20"):
    return tuple(
        pd.date_range(day, periods=96, freq="15min", tz="Asia/Shanghai")
        .tz_convert("UTC")
        .strftime("%Y-%m-%d %H:%M:%S")
    )


@pytest.fixture
def records():
    return read_forecast_files(DIRECTORY)


@pytest.fixture
def provider():
    return LongTableRenewableProvider(
        load_renewable_capacities(ROOT / "config" / "renewable_capacities.json")
    )


def test_native_batch_selects_second_day_and_converts_interval_end(records, provider):
    forecast = provider.load(records, axis())
    farm1 = [r for r in records if r["farmId"] == 1]
    assert len(records) == 19 * 960
    assert forecast.forecast_batch == "202609180800"
    assert forecast.values_mw[0, 0] == farm1[96]["predictedPower"]
    assert farm1[96]["predictedTime"] == "202609200015"
    assert forecast.values_mw[0, -1] == farm1[191]["predictedPower"]
    assert farm1[191]["predictedTime"] == "202609210000"
    assert forecast.values_mw.sum() * 0.25 == pytest.approx(3224.63936330175)


def test_offline_and_inline_paths_use_identical_new_forecasts(records, provider):
    cfg = replace(dispatch_config(), renewable_day="2026-09-20")
    total, values, farms = read_renewable_forecast(cfg)
    direct = provider.load(records, axis())
    np.testing.assert_array_equal(values, direct.values_mw)
    np.testing.assert_array_equal(total, values.sum(axis=0))
    assert farms == list(direct.farm_ids)


@pytest.mark.parametrize("damage", ["duplicate", "mixed_batch", "unknown_farm", "off_grid"])
def test_rejects_incomplete_or_inconsistent_batch(records, provider, damage):
    if damage == "missing":
        records.pop(96)
    elif damage == "duplicate":
        records.append(deepcopy(records[96]))
    elif damage == "mixed_batch":
        records[96]["batch"] = "202609170800"
    elif damage == "unknown_farm":
        records[96]["farmId"] = 999
    else:
        records[96]["predictedTime"] = "202609200016"
    with pytest.raises(RenewableInputError):
        provider.load(records, axis())


def test_preserves_raw_values_but_caps_first_forecast_without_previous(records, provider):
    original = deepcopy(records)
    result = provider.load(records, axis("2026-09-19"))
    assert result.values_mw[0, 0] == 150.8
    assert result.adjustments[0]["original_value"] == 157.955
    assert result.adjustments[0]["action"] == "initial_capacity_limit"
    assert records == original
    with pytest.raises(RenewableInputError, match="缺少字段"):
        provider.load(records, axis("2026-06-06"))
