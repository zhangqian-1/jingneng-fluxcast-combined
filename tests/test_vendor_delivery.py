"""Do not accept one prediction model's package as the other model's delivery."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location(
        "vendor_verifier_test", ROOT / "deploy/forecast-dispatch/verify_vendor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vendor_pair(tmp_path, verifier, monkeypatch):
    records = {}
    for profile in ("single_step", "day_ahead"):
        directory = tmp_path / profile
        directory.mkdir()
        metadata = {
            "image": profile,
            "commit": profile,
            "model": profile,
            "platform": "linux/amd64",
        }
        content = json.dumps(metadata).encode()
        (directory / "release.json").write_bytes(content)
        (directory / "SHA256SUMS").write_text(
            hashlib.sha256(content).hexdigest() + "  release.json\n", "utf-8"
        )
        archive = tmp_path / (profile + ".zip")
        with zipfile.ZipFile(archive, "w") as bundle:
            for path in directory.iterdir():
                bundle.write(path, path.name)
        records[profile] = {
            **metadata,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }
    monkeypatch.setattr(verifier, "release", lambda profile: records[profile], raising=False)
    return tmp_path, records


@pytest.mark.parametrize("profile", ["single_step", "day_ahead"])
def test_matching_original_package_passes(verifier, vendor_pair, profile):
    root, _ = vendor_pair
    assert all(verifier.verify(root / profile, root / (profile + ".zip"), profile=profile).values())


def test_cannot_swap_single_step_archive_for_day_ahead(verifier, vendor_pair):
    root, _ = vendor_pair
    with pytest.raises(ValueError, match="mismatch"):
        verifier.verify(root / "single_step", root / "single_step.zip", profile="day_ahead")


def test_cannot_pair_valid_archive_with_other_extracted_model(verifier, vendor_pair):
    root, _ = vendor_pair
    with pytest.raises(ValueError, match="mismatch"):
        verifier.verify(root / "day_ahead", root / "single_step.zip", profile="single_step")
