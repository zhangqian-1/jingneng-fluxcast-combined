"""Download the two pinned public delivery archives and verify before loading."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/forecast-dispatch"))

from verify_vendor import VENDORS, digest, release, verify  # noqa: E402


def prepare(profile):
    identity = release(profile)
    folder = ROOT / VENDORS[profile]["source_folder"]
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / identity["archive"]
    parsed = urllib.parse.urlsplit(identity["upstream_release"])
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parts[2:4] != ["releases", "tag"]
    ):
        raise ValueError("Expected a pinned GitHub release")
    if archive.name != identity["archive"]:
        raise ValueError("Archive must be a basename")
    url = urllib.parse.urlunsplit(
        (
            "https",
            "github.com",
            "/" + "/".join([*parts[:3], "download", parts[4], archive.name]),
            "",
            "",
        )
    )
    if not archive.exists():
        print(f"Downloading {profile}: {archive.name}", flush=True)
        with tempfile.NamedTemporaryFile(dir=folder, delete=False, suffix=".part") as temporary:
            partial = Path(temporary.name)
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "fluxcast-cloud-build"}
                )
                with urllib.request.urlopen(request, timeout=120) as response:
                    count, logged = 0, 0
                    while block := response.read(4 * 1024 * 1024):
                        temporary.write(block)
                        count += len(block)
                        if count - logged >= 64 * 1024 * 1024:
                            print(f"{profile}: {count // (1024 * 1024)} MiB", flush=True)
                            logged = count
            except BaseException:
                temporary.close()
                partial.unlink(missing_ok=True)
                raise
        if digest(partial) != identity["archive_sha256"]:
            partial.unlink()
            raise ValueError(f"Archive checksum mismatch: {profile}")
        partial.replace(archive)
    if digest(archive) != identity["archive_sha256"]:
        raise ValueError(f"Archive checksum mismatch: {profile}")
    target = folder / "original-package"
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=folder, prefix="extract-") as temporary:
            stage = Path(temporary).resolve()
            with zipfile.ZipFile(archive) as bundle:
                if any(not (stage / n).resolve().is_relative_to(stage) for n in bundle.namelist()):
                    raise ValueError("Archive member outside extraction directory")
                bundle.extractall(stage)
            verify(stage, archive, profile=profile)
            shutil.move(str(stage), str(target))
    verify(target, archive, profile=profile)
    image = target / identity["offline_image"]["file"]
    if digest(image) != identity["offline_image"]["sha256"]:
        raise ValueError(f"Image archive checksum mismatch: {profile}")
    subprocess.run(["docker", "load", "-i", str(image)], check=True)
    print(
        json.dumps({"profile": profile, "image": identity["image"], "verified": True}), flush=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=[*VENDORS, "all"], default="all", nargs="?")
    args = parser.parse_args()
    for profile in VENDORS if args.profile == "all" else [args.profile]:
        prepare(profile)
