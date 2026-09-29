"""Shared runtime defaults for HTTP, offline execution and the dispatch CLI."""

from __future__ import annotations

import math
import os
from pathlib import Path

from dotenv import load_dotenv

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPOSITORY_ROOT / ".env")


def positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def input_directory() -> Path:
    return Path(os.getenv("INPUT_PATH", str(REPOSITORY_ROOT / "data"))).expanduser()


def output_directory() -> Path:
    return Path(os.getenv("OUTPUT_PATH", str(REPOSITORY_ROOT / "output"))).expanduser()
