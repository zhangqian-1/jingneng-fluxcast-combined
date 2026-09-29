"""Extract and verify the vendor ZIP using the already delivered dispatch image."""

import json
import tempfile
import zipfile
from pathlib import Path

from verify_vendor import VENDORS, verify


def unpack(profile):
    vendor = Path(VENDORS[profile]["delivery_folder"]).resolve()
    archive = vendor / "original.zip"
    target = vendor / "unpacked"
    if target.exists():
        print(json.dumps(verify(target, archive, profile=profile)))
        return
    # The final directory appears only after complete extraction and verification.
    with tempfile.TemporaryDirectory(prefix=".unpack-", dir=vendor) as temporary:
        stage = Path(temporary).resolve()
        with zipfile.ZipFile(archive) as bundle:
            if any(
                not (stage / name).resolve().is_relative_to(stage) for name in bundle.namelist()
            ):
                raise ValueError("ZIP entry outside vendor directory")
            bundle.extractall(stage)
        checked = verify(stage, archive, profile=profile)
        stage.rename(target)
        print(json.dumps(checked))


if __name__ == "__main__":
    for profile in VENDORS:
        unpack(profile)
