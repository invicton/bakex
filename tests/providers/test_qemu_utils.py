# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""_qemu_utils.py unit tests — subprocess/network calls mocked, no real QEMU/downloads."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROVIDERS_DIR = Path(__file__).parent.parent.parent / "plugins" / "providers"
_QEMU_UTILS_PATH = _PROVIDERS_DIR / "_qemu_utils.py"

# wait_for_ssh_ready imports _provider_utils by bare name at call time —
# needs this directory on sys.path regardless of what other test modules
# have already done so.
sys.path.insert(0, str(_PROVIDERS_DIR))


def _load_qemu_utils():
    spec = importlib.util.spec_from_file_location("qemu_utils", _QEMU_UTILS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def qemu():
    return _load_qemu_utils()


# ---------------------------------------------------------------------------
# resolve_base_image — BYO path vs. download
# ---------------------------------------------------------------------------


def test_resolve_base_image_byo_path_used_as_is(qemu, tmp_path):
    byo = tmp_path / "my-custom-image.qcow2"
    byo.write_bytes(b"fake qcow2 content")
    result = qemu.resolve_base_image(str(byo), "ubuntu22.04", tmp_path / "cache")
    assert result == byo


def test_resolve_base_image_unknown_os_no_file_raises(qemu, tmp_path):
    with pytest.raises(qemu.BaseImageError, match="No downloadable base image"):
        qemu.resolve_base_image("", "some-unknown-os", tmp_path / "cache")


def test_resolve_base_image_downloads_and_caches(qemu, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"

    def fake_urlretrieve(url, dest):
        Path(dest).write_bytes(b"fake downloaded image content")

    with (
        patch.object(qemu.urllib.request, "urlretrieve", side_effect=fake_urlretrieve),
        patch.object(qemu, "_fetch_expected_checksum", return_value=None),
    ):
        result = qemu.resolve_base_image("", "ubuntu22.04", cache_dir)

    assert result.is_file()
    assert result.read_bytes() == b"fake downloaded image content"
    assert result.with_suffix(result.suffix + ".sha256").is_file()


def test_resolve_base_image_uses_cache_on_second_call(qemu, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    call_count = 0

    def fake_urlretrieve(url, dest):
        nonlocal call_count
        call_count += 1
        Path(dest).write_bytes(b"fake image")

    with (
        patch.object(qemu.urllib.request, "urlretrieve", side_effect=fake_urlretrieve),
        patch.object(qemu, "_fetch_expected_checksum", return_value=None),
    ):
        qemu.resolve_base_image("", "ubuntu22.04", cache_dir)
        qemu.resolve_base_image("", "ubuntu22.04", cache_dir)

    assert call_count == 1, "second call must use the cached file, not re-download"


def test_resolve_base_image_checksum_mismatch_raises(qemu, tmp_path):
    cache_dir = tmp_path / "cache"

    def fake_urlretrieve(url, dest):
        Path(dest).write_bytes(b"fake image content")

    with (
        patch.object(qemu.urllib.request, "urlretrieve", side_effect=fake_urlretrieve),
        patch.object(qemu, "_fetch_expected_checksum", return_value="0" * 64),
    ):
        with pytest.raises(qemu.BaseImageError, match="Checksum mismatch"):
            qemu.resolve_base_image("", "ubuntu22.04", cache_dir)


def test_resolve_base_image_checksum_match_succeeds(qemu, tmp_path):
    cache_dir = tmp_path / "cache"
    content = b"fake image content"

    def fake_urlretrieve(url, dest):
        Path(dest).write_bytes(content)

    import hashlib

    expected = hashlib.sha256(content).hexdigest()
    with (
        patch.object(qemu.urllib.request, "urlretrieve", side_effect=fake_urlretrieve),
        patch.object(qemu, "_fetch_expected_checksum", return_value=expected),
    ):
        result = qemu.resolve_base_image("", "ubuntu22.04", cache_dir)

    assert result.is_file()


# ---------------------------------------------------------------------------
# Disk image lifecycle
# ---------------------------------------------------------------------------


def test_create_overlay_invokes_qemu_img_with_backing_format(qemu, tmp_path):
    base = tmp_path / "base.qcow2"
    base.write_bytes(b"x")
    overlay = tmp_path / "out" / "overlay.qcow2"

    with patch.object(qemu.subprocess, "run") as mock_run:
        qemu.create_overlay(base, overlay)

    args = mock_run.call_args[0][0]
    assert args[0] == "qemu-img"
    assert "-F" in args and "qcow2" in args
    assert str(base.resolve()) in args


def test_create_overlay_with_size_appends_size_arg(qemu, tmp_path):
    base = tmp_path / "base.qcow2"
    base.write_bytes(b"x")
    overlay = tmp_path / "overlay.qcow2"

    with patch.object(qemu.subprocess, "run") as mock_run:
        qemu.create_overlay(base, overlay, size_gb=20)

    args = mock_run.call_args[0][0]
    assert args[-1] == "20G"


def test_create_overlay_without_size_omits_size_arg(qemu, tmp_path):
    base = tmp_path / "base.qcow2"
    base.write_bytes(b"x")
    overlay = tmp_path / "overlay.qcow2"

    with patch.object(qemu.subprocess, "run") as mock_run:
        qemu.create_overlay(base, overlay)

    args = mock_run.call_args[0][0]
    assert not args[-1].endswith("G")


def test_convert_to_raw_invokes_qemu_img_convert(qemu, tmp_path):
    with patch.object(qemu.subprocess, "run") as mock_run:
        qemu.convert_to_raw(tmp_path / "in.qcow2", tmp_path / "out.raw")
    args = mock_run.call_args[0][0]
    assert args[:3] == ["qemu-img", "convert", "-O"]
    assert "raw" in args


# ---------------------------------------------------------------------------
# cloud-init seed ISO
# ---------------------------------------------------------------------------


def test_build_seed_iso_uses_cloud_localds_when_available(qemu, tmp_path):
    with (
        patch.object(qemu.shutil, "which", return_value="/usr/bin/cloud-localds"),
        patch.object(qemu.subprocess, "run") as mock_run,
    ):
        qemu.build_seed_iso(tmp_path, "ssh-rsa AAAA fake", "ubuntu", "test-host")

    assert mock_run.call_args[0][0][0] == "cloud-localds"
    assert (tmp_path / "user-data").is_file()
    assert (tmp_path / "meta-data").is_file()
    assert "ssh-rsa AAAA fake" in (tmp_path / "user-data").read_text()
    assert "lock_passwd: true" in (tmp_path / "user-data").read_text()
    assert "ssh_pwauth: false" in (tmp_path / "user-data").read_text()


def test_build_seed_iso_falls_back_to_genisoimage(qemu, tmp_path):
    with (
        patch.object(qemu.shutil, "which", return_value=None),
        patch.object(qemu.subprocess, "run") as mock_run,
    ):
        qemu.build_seed_iso(tmp_path, "ssh-rsa AAAA fake", "ubuntu", "test-host")

    assert mock_run.call_args[0][0][0] == "genisoimage"


def test_build_seed_iso_never_sets_a_password(qemu, tmp_path):
    with patch.object(qemu.shutil, "which", return_value=None), patch.object(qemu.subprocess, "run"):
        qemu.build_seed_iso(tmp_path, "ssh-rsa AAAA fake", "ubuntu", "test-host")
    user_data = (tmp_path / "user-data").read_text()
    assert "password" not in user_data.lower() or "lock_passwd" in user_data


# ---------------------------------------------------------------------------
# Networking / KVM detection
# ---------------------------------------------------------------------------


def test_find_free_port_returns_usable_port(qemu):
    port = qemu.find_free_port()
    assert isinstance(port, int)
    assert 0 < port < 65536


def test_find_free_port_returns_different_ports(qemu):
    ports = {qemu.find_free_port() for _ in range(5)}
    assert len(ports) > 1, "should not always return the same port"


def test_kvm_available_false_when_no_device(qemu):
    with patch.object(qemu.Path, "exists", return_value=False):
        assert qemu.kvm_available() is False


def test_kvm_available_false_when_not_accessible(qemu):
    with patch.object(qemu.Path, "exists", return_value=True), patch.object(qemu.os, "access", return_value=False):
        assert qemu.kvm_available() is False


def test_kvm_available_true_when_present_and_accessible(qemu):
    with patch.object(qemu.Path, "exists", return_value=True), patch.object(qemu.os, "access", return_value=True):
        assert qemu.kvm_available() is True


# ---------------------------------------------------------------------------
# QEMU process lifecycle
# ---------------------------------------------------------------------------


def test_launch_qemu_uses_kvm_accel_when_available(qemu, tmp_path):
    with (
        patch.object(qemu, "kvm_available", return_value=True),
        patch.object(qemu.subprocess, "Popen") as mock_popen,
    ):
        qemu.launch_qemu(tmp_path / "o.qcow2", tmp_path / "s.iso", 2222, tmp_path / "serial.log")
    args = mock_popen.call_args[0][0]
    assert "accel=kvm" in args


def test_launch_qemu_falls_back_to_tcg(qemu, tmp_path):
    with (
        patch.object(qemu, "kvm_available", return_value=False),
        patch.object(qemu.subprocess, "Popen") as mock_popen,
    ):
        qemu.launch_qemu(tmp_path / "o.qcow2", tmp_path / "s.iso", 2222, tmp_path / "serial.log")
    args = mock_popen.call_args[0][0]
    assert "accel=tcg" in args


def test_launch_qemu_redirects_serial_to_file_not_pipe(qemu, tmp_path):
    """Guest console output must go to a file — an unconsumed pipe can fill
    its OS buffer and block QEMU on write() during a long build."""
    with patch.object(qemu.subprocess, "Popen") as mock_popen:
        qemu.launch_qemu(tmp_path / "o.qcow2", tmp_path / "s.iso", 2222, tmp_path / "serial.log")
    args = mock_popen.call_args[0][0]
    assert any(a.startswith("file:") for a in args if isinstance(a, str))
    _, kwargs = mock_popen.call_args
    assert kwargs.get("stdout") != subprocess.PIPE
    assert kwargs.get("stderr") != subprocess.PIPE


def test_launch_qemu_forwards_ssh_port(qemu, tmp_path):
    with patch.object(qemu.subprocess, "Popen") as mock_popen:
        qemu.launch_qemu(tmp_path / "o.qcow2", tmp_path / "s.iso", 45678, tmp_path / "serial.log")
    args = mock_popen.call_args[0][0]
    assert any("hostfwd=tcp::45678-:22" in a for a in args if isinstance(a, str))


def test_terminate_qemu_noop_if_already_exited(qemu):
    proc = MagicMock()
    proc.poll.return_value = 0
    qemu.terminate_qemu(proc)
    proc.terminate.assert_not_called()


def test_terminate_qemu_kills_if_terminate_times_out(qemu):
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="qemu", timeout=30), None]
    qemu.terminate_qemu(proc)
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()


def test_wait_for_process_exit_true_on_clean_exit(qemu):
    proc = MagicMock()
    proc.wait.return_value = 0
    assert qemu.wait_for_process_exit(proc, timeout=5) is True


def test_wait_for_process_exit_false_on_timeout(qemu):
    proc = MagicMock()
    proc.wait.side_effect = subprocess.TimeoutExpired(cmd="qemu", timeout=5)
    assert qemu.wait_for_process_exit(proc, timeout=5) is False


# ---------------------------------------------------------------------------
# wait_for_ssh_ready — retries on ANY failure, unlike the keyword-matching
# retry used elsewhere, because sshd's early-boot failure mode is inconsistent
# from run to run (sometimes a named error, sometimes none at all).
# ---------------------------------------------------------------------------


def test_wait_for_ssh_ready_succeeds_immediately(qemu, tmp_path):
    with patch("_provider_utils.run_remote_cmd") as mock_cmd:
        qemu.wait_for_ssh_ready("127.0.0.1", "ubuntu", tmp_path / "key", port=2222, timeout=10)
    mock_cmd.assert_called_once()


def test_wait_for_ssh_ready_retries_on_unrecognized_error(qemu, tmp_path):
    """A RuntimeError with no matching keyword (e.g. an empty message) must
    still be retried here — unlike run_remote_cmd_with_retry, which would
    re-raise immediately since it only retries known error-text patterns."""
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Remote command failed (exit 255):\nCMD: true\nSTDOUT: \nSTDERR: ")
        return (0, "", "")

    with patch("_provider_utils.run_remote_cmd", side_effect=flaky):
        qemu.wait_for_ssh_ready("127.0.0.1", "ubuntu", tmp_path / "key", port=2222, timeout=10, interval=0.01)
    assert calls["n"] == 3


def test_wait_for_ssh_ready_raises_timeout_error_eventually(qemu, tmp_path):
    with patch("_provider_utils.run_remote_cmd", side_effect=RuntimeError("still not ready")):
        with pytest.raises(TimeoutError, match="did not become truly ready"):
            qemu.wait_for_ssh_ready("127.0.0.1", "ubuntu", tmp_path / "key", port=2222, timeout=0.2, interval=0.05)
