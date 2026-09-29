"""Image export must stream, propagate Docker failures, and discard partial files."""

import gzip
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def packager():
    spec = importlib.util.spec_from_file_location(
        "package_export_test", ROOT / "scripts/package_forecast_dispatch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_docker(packager, monkeypatch, code):
    original = subprocess.Popen

    def launch(command, **kwargs):
        assert command == ["docker", "save", "test-image"]
        assert kwargs == {"stdout": subprocess.PIPE}
        return original([sys.executable, "-c", code], **kwargs)

    monkeypatch.setattr(packager.subprocess, "Popen", launch)


def test_export_streams_to_valid_gzip(packager, monkeypatch, tmp_path):
    data = b"fixture archive\n" * 100000
    fake_docker(
        packager, monkeypatch, "import sys; sys.stdout.buffer.write(b'fixture archive\\n'*100000)"
    )
    destination = tmp_path / "image.tar.gz"
    packager.export_image("test-image", destination)
    assert gzip.decompress(destination.read_bytes()) == data
    assert list(tmp_path.iterdir()) == [destination]


def test_failed_export_does_not_publish_partial_archive(packager, monkeypatch, tmp_path):
    fake_docker(packager, monkeypatch, "import sys; print('partial'); sys.exit(7)")
    with pytest.raises(subprocess.CalledProcessError) as error:
        packager.export_image("test-image", tmp_path / "image.tar.gz")
    assert error.value.returncode == 7
    assert not list(tmp_path.iterdir())


def test_compression_failure_cleans_partial_archive(packager, monkeypatch, tmp_path):
    fake_docker(packager, monkeypatch, "print('fixture')")

    def fail_copy(source, destination, **kwargs):
        destination.write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(packager.shutil, "copyfileobj", fail_copy)
    with pytest.raises(OSError, match="disk full"):
        packager.export_image("test-image", tmp_path / "image.tar.gz")
    assert not list(tmp_path.iterdir())
