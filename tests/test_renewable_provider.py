from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.platform_config import RENEWABLE_FARM_IDS, load_renewable_capacities
from src.renewable_provider import (
    InlineRenewableProvider,
    RenewableInputError,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def capacities() -> dict[int, float]:
    return load_renewable_capacities(CONFIG_DIR / "renewable_capacities.json")


def renewable_frames() -> list[dict[str, object]]:
    result = []
    limits = capacities()
    for period in range(96):
        frame: dict[str, object] = {
            "timestamp": (datetime(2026, 6, 6) + timedelta(minutes=15 * period)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }
        frame.update({f"farm_{farm_id}_predictedPower": limits[farm_id] / 2 for farm_id in limits})
        result.append(frame)
    return result


def normalized_axis() -> tuple[str, ...]:
    return tuple(
        (datetime(2026, 6, 5, 16) + timedelta(minutes=15 * period)).strftime("%Y-%m-%d %H:%M:%S")
        for period in range(96)
    )


def test_inline_provider_returns_nineteen_by_ninety_six_matrix() -> None:
    result = InlineRenewableProvider(capacities()).load(renewable_frames(), normalized_axis())

    assert result.farm_ids == RENEWABLE_FARM_IDS
    assert result.values_mw.shape == (19, 96)
    assert len(result.payload_hash) == 64


def test_provider_caps_first_capacity_violation_without_previous() -> None:
    frames = renewable_frames()
    frames[0]["farm_1_predictedPower"] = capacities()[1] + 0.001

    result = InlineRenewableProvider(capacities()).load(frames, normalized_axis())
    assert result.values_mw[0, 0] == capacities()[1]
    assert result.adjustments[0]["action"] == "initial_capacity_limit"


def test_provider_carries_missing_field() -> None:
    frames = renewable_frames()
    del frames[9]["farm_29_predictedPower"]

    result = InlineRenewableProvider(capacities()).load(frames, normalized_axis())
    assert result.values_mw[-1, 9] == result.values_mw[-1, 8]
    assert len(result.adjustments) == 1


@pytest.mark.parametrize("bad_frame", [None, [], "invalid"])
def test_provider_rejects_non_object_frames(bad_frame):
    frames = renewable_frames()
    frames[0] = bad_frame
    with pytest.raises(RenewableInputError, match="JSON对象"):
        InlineRenewableProvider(capacities()).load(frames, normalized_axis())
