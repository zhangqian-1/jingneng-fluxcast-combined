"""Check packaged business data and Linux ARM dependency availability."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_BINARY_WHEELS = (
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("pandas", "pandas"),
    ("pydantic_core", "pydantic_core"),
    ("httptools", "httptools"),
    ("uvloop", "uvloop"),
)
PYTHON_TAGS = ("cp310", "cp311")


def missing_arm_wheels(lock_text: str) -> list[str]:
    """Return readable labels for required Linux aarch64 wheels absent from uv.lock."""

    missing: list[str] = []
    for label, distribution in REQUIRED_BINARY_WHEELS:
        for python_tag in PYTHON_TAGS:
            pattern = rf"{re.escape(distribution)}-[^\"\s]*{python_tag}[^\"\s]*aarch64[^\"\s]*\.whl"
            if re.search(pattern, lock_text) is None:
                missing.append(f"{label} {python_tag}")
    return missing


def check_input_data(data_dir: Path = ROOT / "data") -> dict[str, int]:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    records = manifest["files"]
    counts = {".csv": 0, ".json": 0, ".xlsx": 0}
    paths = set()
    total_bytes = 0
    for record in records:
        name = record["path"]
        if name in paths:
            raise ValueError(f"Duplicate input in manifest: {name}")
        paths.add(name)
        path = (data_dir / name).resolve()
        if not path.is_relative_to(data_dir.resolve()):
            raise ValueError(f"Input escapes data directory: {name}")
        content = path.read_bytes()
        if len(content) != record["bytes"]:
            raise ValueError(f"Input size mismatch: {name}")
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise ValueError(f"Input SHA-256 mismatch: {name}")
        counts[path.suffix] += 1
        total_bytes += len(content)
    if counts != {".csv": 7, ".json": 19, ".xlsx": 2}:
        raise ValueError(f"Expected 7 CSV, 19 JSON, 2 Excel: {counts}")
    return {"files": len(records), "bytes": total_bytes, **counts}


def main() -> None:
    missing = missing_arm_wheels((ROOT / "uv.lock").read_text(encoding="utf-8"))
    if missing:
        raise SystemExit(f"Missing Linux ARM wheels: {', '.join(missing)}")
    print(json.dumps({"inputs": check_input_data(), "arm_wheels": "passed"}))


if __name__ == "__main__":
    main()
