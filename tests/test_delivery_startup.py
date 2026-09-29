"""Execute delivery launchers with a fake Docker to observe their Compose environment."""

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGED_IMAGE = "jingneng-fluxcast-all-in-one:20260929-r2"


class DeliveryImageSelectionTests(unittest.TestCase):
    def run_launcher(self, shell, inherited):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "service/deploy/forecast-dispatch"
            config.mkdir(parents=True)
            (config / ".env.example").write_text(f"DISPATCH_IMAGE={PACKAGED_IMAGE}\n", "utf-8")
            data = b"fixture; docker import is intercepted\n"
            (root / "dispatch-image.tar.gz").write_bytes(data)
            (root / "SHA256SUMS").write_text(
                hashlib.sha256(data).hexdigest() + "  dispatch-image.tar.gz\n", "utf-8"
            )
            capture = root / "compose-image.txt"
            env = {**os.environ, "TEST_CAPTURE": str(capture)}
            env.pop("DISPATCH_IMAGE", None)
            if inherited is not None:
                env["DISPATCH_IMAGE"] = inherited
            source = ROOT / f"deploy/forecast-dispatch/start-delivery.{shell}"
            shutil.copyfile(source, root / f"start.{shell}")
            if shell == "sh":
                fake_bin = root / "bin"
                fake_bin.mkdir()
                docker = fake_bin / "docker"
                docker.write_text(
                    '#!/bin/sh\nif [ "$1" = compose ]; then\n'
                    '  printf "%s\\n" "${DISPATCH_IMAGE-unset}" >> "$TEST_CAPTURE"\n'
                    "fi\nexit 0\n",
                    "utf-8",
                )
                docker.chmod(0o755)
                env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
                command = ["/bin/sh", str(root / "start.sh")]
            else:
                # A PowerShell 7 parent may export module paths incompatible with 5.1.
                env = {k: v for k, v in env.items() if k.lower() != "psmodulepath"}
                wrapper = root / "invoke.ps1"
                wrapper.write_text(
                    "function global:docker {\n"
                    "  if ($args[0] -eq 'compose') {\n"
                    "    Add-Content -LiteralPath $env:TEST_CAPTURE "
                    "-Value $env:DISPATCH_IMAGE -Encoding UTF8\n"
                    "  }\n  $global:LASTEXITCODE = 0\n}\n"
                    "& (Join-Path $PSScriptRoot 'start.ps1')\n",
                    "utf-8",
                )
                command = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(wrapper),
                ]
            completed = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            self.assertEqual(capture.read_text("utf-8-sig").splitlines(), [PACKAGED_IMAGE])

    @unittest.skipIf(os.name == "nt", "POSIX shell is tested on Linux")
    def test_posix_replaces_stale_image(self):
        self.run_launcher("sh", "jingneng-single-period-dispatch:20260922")

    @unittest.skipIf(os.name == "nt", "POSIX shell is tested on Linux")
    def test_posix_without_override(self):
        self.run_launcher("sh", None)

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell is tested on Windows")
    def test_powershell_replaces_stale_image(self):
        self.run_launcher("ps1", "jingneng-single-period-dispatch:20260922")

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell is tested on Windows")
    def test_powershell_without_override(self):
        self.run_launcher("ps1", None)


if __name__ == "__main__":
    unittest.main()
