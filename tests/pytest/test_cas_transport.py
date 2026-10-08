"""Unit tests for scripts/cas-transport.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
spec = importlib.util.spec_from_file_location("cas_transport", scripts_dir / "cas-transport.py")
assert spec and spec.loader
cas_transport = importlib.util.module_from_spec(spec)
sys.modules["cas_transport"] = cas_transport
spec.loader.exec_module(cas_transport)


def test_format_cas_ref_x86_64():
    ref = cas_transport.format_cas_ref(
        repo="Tuna-OS/Tromso",
        image_name="tromso",
        arch="x86_64",
        target_type="core",
        tag="latest",
    )
    assert ref == "ghcr.io/tuna-os/tromso/cache-tromso-core:latest"


def test_format_cas_ref_aarch64():
    ref = cas_transport.format_cas_ref(
        repo="tuna-os/tromso",
        image_name="tromso",
        arch="aarch64",
        target_type="deps-chunk-1",
        tag="abc1234",
    )
    assert ref == "ghcr.io/tuna-os/tromso/cache-tromso-aarch64-deps-chunk-1:abc1234"


def test_check_manifest_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert cas_transport.check_manifest("ghcr.io/repo/cache:tag") is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["oras", "manifest", "fetch", "ghcr.io/repo/cache:tag"]


def test_check_manifest_failure():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert cas_transport.check_manifest("ghcr.io/repo/cache:tag") is False


def test_check_manifest_exception():
    with patch("subprocess.run", side_effect=OSError("oras not found")):
        assert cas_transport.check_manifest("ghcr.io/repo/cache:tag") is False


def test_pull_and_extract_cas_success(tmp_path):
    dest_dir = tmp_path / "cache"
    archive_file = tmp_path / "cas.tar.zst"
    archive_file.write_text("dummy")

    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen, \
         patch("os.path.isfile", return_value=True), \
         patch("os.remove") as mock_remove:
        mock_run.return_value = MagicMock(returncode=0)

        mock_zstd = MagicMock()
        mock_zstd.returncode = 0
        mock_zstd.stdout = MagicMock()
        mock_zstd.wait.return_value = 0

        mock_tar = MagicMock()
        mock_tar.returncode = 0
        mock_tar.communicate.return_value = (b"", b"")

        mock_popen.side_effect = [mock_zstd, mock_tar]

        ok = cas_transport.pull_and_extract_cas("ghcr.io/repo/cache:tag", str(archive_file), str(dest_dir))
        assert ok is True
        mock_remove.assert_called_once_with(str(archive_file))


def test_pull_and_extract_cas_pull_fails(tmp_path):
    dest_dir = tmp_path / "cache"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        ok = cas_transport.pull_and_extract_cas("ghcr.io/repo/cache:tag", "cas.tar.zst", str(dest_dir))
        assert ok is False


def test_archive_cas_success(tmp_path):
    src_dir = tmp_path / "input"
    src_dir.mkdir()
    out_archive = tmp_path / "output" / "cas.tar.zst"

    with patch("subprocess.run") as mock_run, patch("os.path.isfile", return_value=True):
        mock_run.return_value = MagicMock(returncode=0)
        ok = cas_transport.archive_cas("ghcr.io/tuna-os/bst2:latest", str(src_dir), str(out_archive))
        assert ok is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "podman"
        assert "run" in cmd
        assert "--exclude 'cas/staging' --exclude 'cas/tmp'" in cmd[-1]


def test_push_cas_with_retry_success():
    with patch("os.path.isfile", return_value=True), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ok = cas_transport.push_cas_with_retry("ghcr.io/repo/cache:tag", "/tmp/cas.tar.zst", max_retries=2)
        assert ok is True
        mock_run.assert_called_once()


def test_push_cas_with_retry_failure():
    with patch("os.path.isfile", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("time.sleep"):
        mock_run.return_value = MagicMock(returncode=1, stderr="unauthorized")
        ok = cas_transport.push_cas_with_retry(
            "ghcr.io/repo/cache:tag",
            "/tmp/cas.tar.zst",
            max_retries=2,
            soft_fail=True,
        )
        assert ok is False
        assert mock_run.call_count == 2


def test_main_cli_ref(capsys):
    ret = cas_transport.main([
        "ref",
        "--repo", "tuna-os/tromso",
        "--image", "tromso",
        "--arch", "x86_64",
        "--type", "core",
        "--tag", "latest",
    ])
    assert ret == 0
    captured = capsys.readouterr()
    assert "ghcr.io/tuna-os/tromso/cache-tromso-core:latest" in captured.out


def test_main_cli_check():
    with patch.object(cas_transport, "check_manifest", return_value=True):
        ret = cas_transport.main(["check", "ghcr.io/repo/cache:tag"])
        assert ret == 0

    with patch.object(cas_transport, "check_manifest", return_value=False):
        ret = cas_transport.main(["check", "ghcr.io/repo/cache:tag"])
        assert ret == 1
