"""Verify the original delivery without writing to it."""

import argparse
import hashlib
import json
from pathlib import Path

VENDORS = {
    "single_step": {
        "manifest": "vendor-release.json",
        "source_folder": "output/forecast-single-step/vendor",
        "delivery_folder": "vendor",
    },
    "day_ahead": {
        "manifest": "vendor-day-release.json",
        "source_folder": "output/forecast-integration/vendor",
        "delivery_folder": "vendor/day",
    },
}


def release(profile):
    return json.loads((Path(__file__).parent / VENDORS[profile]["manifest"]).read_text("utf-8"))


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def verify(directory, archive=None, *, profile="single_step"):
    directory = directory.resolve()
    results = {}
    expected_release = release(profile)
    if archive:
        results[archive.name] = digest(archive) == expected_release["archive_sha256"]
    for line in (directory / "SHA256SUMS").read_text("utf-8").splitlines():
        expected, filename = line.split(None, 1)
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("Checksum entry outside vendor directory")
        results[filename] = digest(path) == expected
    actual_release = json.loads((directory / "release.json").read_text("utf-8"))
    results["release_identity"] = all(
        actual_release.get(key) == expected_release[key]
        for key in ("image", "commit", "model", "platform")
    )
    if not all(results.values()):
        raise ValueError(f"Vendor checksum mismatch: {results}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--profile", choices=VENDORS, default="single_step")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.directory, args.zip, profile=args.profile), ensure_ascii=False, indent=2
        )
    )
