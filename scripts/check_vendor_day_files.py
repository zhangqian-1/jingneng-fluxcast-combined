"""Compare the pinned offline image's vendor files with the current local predictor."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path


def inventory(archive):
    manifests = None
    layers = {}
    with zipfile.ZipFile(archive) as delivery, delivery.open("image.tar.gz") as image:
        with tarfile.open(fileobj=image, mode="r|gz") as outer:
            for entry in outer:
                if not entry.isfile():
                    continue
                stream = outer.extractfile(entry)
                if entry.name == "manifest.json":
                    manifests = json.load(stream)
                elif entry.size > 1024 and entry.name.startswith("blobs/sha256/"):
                    try:
                        with tarfile.open(fileobj=stream, mode="r|*") as layer:
                            files = {}
                            for member in layer:
                                name = member.name.removeprefix("./")
                                if member.isfile() and (
                                    name.startswith(("app/app/", "app/models/"))
                                    or name == "app/requirements.txt"
                                ):
                                    files[name.removeprefix("app/")] = hashlib.file_digest(
                                        layer.extractfile(member), "sha256"
                                    ).hexdigest()
                            layers[entry.name] = files
                    except tarfile.ReadError:
                        pass  # Image config and OCI manifest blobs are JSON, not layers.
    if not manifests or len(manifests) != 1:
        raise ValueError("Expected one saved image")
    files = {}
    for name in manifests[0]["Layers"]:
        files.update(layers[name])
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = (
        Path(__file__).resolve().parents[1] / "deploy/forecast-dispatch/vendor-day-release.json"
    )
    identity = json.loads(manifest_path.read_text("utf-8"))
    with args.archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert digest == identity["archive_sha256"], "Not the pinned day image archive"
    old = inventory(args.archive)
    current = {
        name: hashlib.sha256((args.vendor_root / name).read_bytes()).hexdigest() for name in old
    }
    differences = [name for name in old if old[name] != current[name]]
    report = {
        "image": identity["image"],
        "commit": identity["commit"],
        "files": len(old),
        "different_files": differences,
        "passed": len(old) == 22 and not differences,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
