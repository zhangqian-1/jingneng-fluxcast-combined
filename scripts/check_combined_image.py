"""Verify both original model/code trees and dependency versions inside one image."""

import argparse
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = """
import hashlib, importlib.metadata as metadata, json, sys
from pathlib import Path
root = Path(sys.argv[1])
paths = [root/'requirements.txt']
for name in ('app', 'models'):
    paths += [p for p in (root/name).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts]
files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
print(json.dumps({'files': files,
                  'packages': {p.metadata['Name']:p.version for p in metadata.distributions()},
                  'python': list(sys.version_info[:3])}))
"""


def inventory(image, python, root):
    return json.loads(
        subprocess.check_output(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                python,
                image,
                "-c",
                INVENTORY,
                root,
            ],
            text=True,
            encoding="utf-8",
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checked = {}
    for name, manifest, python, root in (
        ("single_step", "vendor-release.json", "/usr/local/bin/python", "/opt/forecast-single"),
        ("day_ahead", "vendor-day-release.json", "/opt/day-venv/bin/python", "/opt/forecast-day"),
    ):
        original = json.loads((ROOT / "deploy/forecast-dispatch" / manifest).read_text("utf-8"))
        info = json.loads(
            subprocess.check_output(["docker", "image", "inspect", original["image"]], text=True)
        )[0]
        identity = info["Id"]
        # containerd image stores can expose an OCI manifest ID instead of the
        # original Docker config ID. Verify the actual rootfs against that config.
        folder = "forecast-single-step" if name == "single_step" else "forecast-integration"
        archive = ROOT / f"output/{folder}/vendor/original-package/image.tar.gz"
        checksum = hashlib.sha256()
        with archive.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(block)
        assert checksum.hexdigest() == original["offline_image"]["sha256"], name
        expected = original["image_id"].split(":")[1]
        config = None
        with tarfile.open(archive, "r|gz") as bundle:
            for entry in bundle:
                if entry.isfile() and Path(entry.name).name.removesuffix(".json") == expected:
                    raw = bundle.extractfile(entry).read()
                    assert hashlib.sha256(raw).hexdigest() == expected
                    config = json.loads(raw)
                    break
        assert config is not None, f"Missing original {name} image config"
        assert info["RootFS"]["Layers"] == config["rootfs"]["diff_ids"], name
        assert info["Architecture"] == config["architecture"], name
        before = inventory(original["image"], "/usr/local/bin/python", "/app")
        after = inventory(args.image, python, root)
        assert before["python"] == after["python"], name
        assert before["files"] == after["files"], f"Changed original {name} code/model"
        assert all(after["packages"].get(k) == v for k, v in before["packages"].items()), name
        checked[name] = {
            "code_model_files": len(before["files"]),
            "dependencies": len(before["packages"]),
            "original_image_id": identity,
        }
    report = {
        "passed": True,
        "models": checked,
        "image_id": subprocess.check_output(
            ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], text=True
        ).strip(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
