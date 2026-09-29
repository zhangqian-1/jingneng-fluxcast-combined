"""Package one verified combined image, source, and original model provenance."""

import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/forecast-dispatch"
sys.path.insert(0, str(DEPLOY))

from verify_vendor import VENDORS, digest, release, verify  # noqa: E402


def export_image(image: str, destination: Path) -> None:
    """Compress the Docker stream without storing a second, uncompressed archive."""
    partial = destination.with_suffix(destination.suffix + ".part")
    command = ["docker", "save", image]
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
            try:
                with gzip.open(partial, "wb", compresslevel=3) as stream:
                    shutil.copyfileobj(process.stdout, stream, length=1024 * 1024)
            except BaseException:
                process.kill()
                raise
            finally:
                process.stdout.close()
            if returncode := process.wait():
                raise subprocess.CalledProcessError(returncode, command)
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version", required=True, help="Unique delivery version, e.g. 20260926-r3"
    )
    parser.add_argument("--image", default="jingneng-fluxcast-all-in-one:20260929-observations")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    version = args.version
    if not re.fullmatch(r"[0-9]{8}(?:-[a-z0-9]+)?", version):
        raise ValueError("Delivery version must be YYYYMMDD with an optional lowercase suffix")
    delivery = ROOT / f"output/combined-delivery-{version}"
    archive = ROOT / f"output/jingneng-fluxcast-combined-amd64-{version}.zip"
    if delivery.exists() or archive.exists():
        raise ValueError(
            "Choose a new version; existing deliveries must not be reused or overwritten"
        )
    # Compare the actual image filesystem to this source tree before packaging.
    inventory_code = """import hashlib, json
from pathlib import Path
root=Path('/app')
paths=[root/n for n in ('api.py','start.sh','pyproject.toml','uv.lock')]
for folder in ('src','config','data','dashboard'):
    paths.extend(p for p in (root/folder).rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts)
print(json.dumps({p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in paths}))
"""
    image_files = json.loads(
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "/app/.venv/bin/python",
                args.image,
                "-c",
                inventory_code,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    )
    source_paths = [ROOT / n for n in ("api.py", "start.sh", "pyproject.toml", "uv.lock")]
    for folder in ("src", "config", "data", "dashboard"):
        source_paths.extend(
            p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    source_files = {p.relative_to(ROOT).as_posix(): digest(p) for p in source_paths}
    if source_files != image_files:
        raise ValueError("Dispatch image differs from current source; rebuild before packaging")
    verification = json.loads((args.evidence / "verification.json").read_text("utf-8"))
    combined = json.loads((args.evidence / "combined-image.json").read_text("utf-8"))
    lifecycle = json.loads((args.evidence / "lifecycle.json").read_text("utf-8"))
    image_id = subprocess.check_output(
        ["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], text=True
    ).strip()
    if (
        not verification.get("passed")
        or not verification.get("platform_contract_verified")
        or not verification.get("dual_forecast_verified")
        or verification.get("day_forecast_points") != 96
        or verification.get("runtime_sha256") != image_files
        or not verification.get("single_container_verified")
        or not verification.get("single_public_port_verified")
        or not verification.get("daily_calendar_curve_verified")
        or not verification.get("calendar_recovery_verified")
        or not verification.get("recovery_preserves_online_cache")
        or not verification.get("observations_contract_verified")
        or not verification.get("initial_deviation_contract_verified")
        or not verification.get("day_history_only_verified")
        or verification.get("platform_response_points") not in (126, 127, 128)
        or verification.get("image_id") != image_id
        or not combined.get("passed")
        or combined.get("image_id") != image_id
        or not lifecycle.get("passed")
        or lifecycle.get("image_id") != image_id
    ):
        raise ValueError("Fresh container verification for this exact runtime is required")
    originals = {}
    checks = {}
    for profile, config in VENDORS.items():
        vendor = ROOT / config["source_folder"]
        original = vendor / release(profile)["archive"]
        checks[profile] = verify(vendor / "original-package", original, profile=profile)
        originals[profile] = original
    delivery.mkdir()
    image = delivery / "dispatch-image.tar.gz"
    export_image(args.image, image)
    # The delivered image already contains both models and their environments.
    # Keep source identity evidence, not two additional runnable image archives.
    (delivery / "vendor-provenance.json").write_text(
        json.dumps({profile: release(profile) for profile in originals}, indent=2), "utf-8"
    )
    service = delivery / "service"
    service.mkdir(exist_ok=True)
    for folder in (
        "src",
        "config",
        "data",
        "dashboard",
        "deploy",
        "docs",
        "tests",
        "examples",
        "scripts",
    ):
        shutil.copytree(
            ROOT / folder,
            service / folder,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache", "*.pyc"),
        )
    for filename in (
        "api.py",
        "Dockerfile",
        "start.sh",
        "pyproject.toml",
        "uv.lock",
        "README.md",
        ".dockerignore",
        ".env.example",
    ):
        shutil.copy2(ROOT / filename, service / filename)
    env_path = service / "deploy/forecast-dispatch/.env.example"
    env_lines = [
        line
        for line in env_path.read_text("utf-8").splitlines()
        if not line.startswith("DISPATCH_IMAGE=")
    ]
    env_path.write_text("\n".join([*env_lines, f"DISPATCH_IMAGE={args.image}"]) + "\n", "utf-8")
    shutil.copy2(DEPLOY / "start-delivery.ps1", delivery / "start.ps1")
    shutil.copy2(DEPLOY / "start-delivery.sh", delivery / "start.sh")
    (delivery / "使用说明.md").write_text(
        (DEPLOY / "README.md").read_text("utf-8").replace("../../docs/", "service/docs/"), "utf-8"
    )
    display = ROOT / "output/single-period-dashboard-share"
    if display.is_dir():
        shutil.copytree(display, delivery / "展示")
    # Clean CI checkouts have no separately exported historical study. The
    # unchanged dashboard and its assets are already included under service/.
    evidence = delivery / "联调记录"
    evidence.mkdir(exist_ok=True)
    for path in args.evidence.glob("*.json"):
        shutil.copy2(path, evidence / path.name)
    (evidence / "原包校验.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), "utf-8"
    )
    manifest = []
    files = [
        path
        for path in sorted(delivery.rglob("*"))
        if path.is_file()
        and path != delivery / "SHA256SUMS"
        and "unpacked" not in path.relative_to(delivery).parts
    ]
    for path in files:
        manifest.append(f"{digest(path)}  {path.relative_to(delivery).as_posix()}")
    (delivery / "SHA256SUMS").write_text("\n".join(manifest) + "\n", "utf-8")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as bundle:
        for path in [*files, delivery / "SHA256SUMS"]:
            compression = (
                zipfile.ZIP_STORED if path.suffix in (".zip", ".gz") else zipfile.ZIP_DEFLATED
            )
            bundle.write(path, path.relative_to(delivery).as_posix(), compress_type=compression)
    checksum = digest(archive)
    archive.with_suffix(".sha256").write_text(f"{checksum}  {archive.name}\n", "utf-8")
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
    print(
        json.dumps(
            {
                "archive": str(archive),
                "bytes": archive.stat().st_size,
                "sha256": checksum,
                "vendor_unchanged": list(originals),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
