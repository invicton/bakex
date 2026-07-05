# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""KVM/QEMU local provider unit tests — subprocess/network calls mocked, no real VM."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_KVM_PATH = Path(__file__).parent.parent.parent / "plugins" / "providers" / "kvm.py"


def _load_kvm():
    spec = importlib.util.spec_from_file_location("kvm_provider", _KVM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def kvm():
    return _load_kvm()


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------


def test_provider_name_is_kvm(kvm):
    assert kvm.PROVIDER_NAME == "kvm"


def test_dispatch_contains_required_methods(kvm):
    assert "execute_build" in kvm._DISPATCH
    assert "test_connection" in kvm._DISPATCH
    assert "list_images" in kvm._DISPATCH


def test_all_dispatch_values_callable(kvm):
    for fn in kvm._DISPATCH.values():
        assert callable(fn)


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


def test_connection_missing_binaries_raises(kvm):
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="Missing required binaries"):
            kvm.test_connection({})


def test_connection_missing_seed_tool_raises(kvm):
    def which(name):
        return "/usr/bin/" + name if name in ("qemu-system-x86_64", "qemu-img") else None

    with patch("shutil.which", side_effect=which):
        with pytest.raises(RuntimeError, match="cloud-localds.*genisoimage|genisoimage.*cloud-localds"):
            kvm.test_connection({})


def test_connection_success_reports_kvm_status(kvm):
    with patch("shutil.which", return_value="/usr/bin/x"), patch.object(kvm.qemu, "kvm_available", return_value=True):
        result = kvm.test_connection({})
    assert result["status"] == "ok"
    assert result["kvm_acceleration"] is True


def test_connection_reports_tcg_fallback(kvm):
    with (
        patch("shutil.which", return_value="/usr/bin/x"),
        patch.object(kvm.qemu, "kvm_available", return_value=False),
    ):
        result = kvm.test_connection({})
    assert result["kvm_acceleration"] is False


# ---------------------------------------------------------------------------
# list_images
# ---------------------------------------------------------------------------


def test_list_images_empty_when_no_builds_dir(kvm, tmp_path, monkeypatch):
    monkeypatch.setattr(kvm, "_BUILDS_DIR", tmp_path / "nonexistent")
    result = kvm.list_images({})
    assert result == {"images": []}


def test_list_images_returns_builds_with_metadata(kvm, tmp_path, monkeypatch):
    builds_dir = tmp_path / "builds"
    build1 = builds_dir / "job-1"
    build1.mkdir(parents=True)
    (build1 / "metadata.json").write_text(
        json.dumps({"profile_name": "test-profile", "output_format": "qcow2", "size_bytes": 123, "os": "ubuntu22.04"})
    )
    # A directory with no metadata.json (e.g. a failed/in-progress build) is skipped
    build2 = builds_dir / "job-2"
    build2.mkdir(parents=True)

    monkeypatch.setattr(kvm, "_BUILDS_DIR", builds_dir)
    result = kvm.list_images({})
    assert len(result["images"]) == 1
    assert result["images"][0]["id"] == "job-1"
    assert result["images"][0]["name"] == "test-profile"


# ---------------------------------------------------------------------------
# execute_build — orchestration, with qemu/_provider_utils mocked out
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_build_env(kvm, tmp_path, monkeypatch):
    """Patch every qemu/_provider_utils call execute_build makes, so it runs
    end-to-end against fakes instead of real subprocess/QEMU/SSH calls."""
    monkeypatch.setattr(kvm, "_LOCAL_IMAGES_DIR", tmp_path / "local-images")
    monkeypatch.setattr(kvm, "_BUILDS_DIR", tmp_path / "builds")

    base_image = tmp_path / "base.qcow2"
    base_image.write_bytes(b"fake-base-image")

    fake_proc = MagicMock()
    fake_proc.poll.return_value = 0

    def fake_create_overlay(base_path, overlay_path, size_gb=None):
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_path.write_bytes(b"fake overlay content")

    def fake_convert_to_raw(qcow2_path, raw_path):
        raw_path.write_bytes(b"fake raw content")

    with (
        patch.object(kvm.qemu, "resolve_base_image", return_value=base_image),
        patch.object(kvm.qemu, "create_overlay", side_effect=fake_create_overlay) as mock_create_overlay,
        patch.object(kvm.qemu, "build_seed_iso", return_value=tmp_path / "seed.iso"),
        patch.object(kvm.qemu, "find_free_port", return_value=54321),
        patch.object(kvm.qemu, "launch_qemu", return_value=fake_proc) as mock_launch,
        patch.object(kvm.qemu, "wait_for_process_exit", return_value=True),
        patch.object(kvm.qemu, "terminate_qemu") as mock_terminate,
        patch.object(kvm.qemu, "convert_to_raw", side_effect=fake_convert_to_raw) as mock_convert,
        patch.object(kvm.qemu, "sha256_file", return_value="deadbeef" * 8),
        patch.object(kvm.utils, "generate_ssh_keypair", return_value=(tmp_path / "key", "ssh-rsa AAAA fake")),
        patch.object(kvm.utils, "wait_for_ssh"),
        patch.object(kvm.utils, "run_remote_cmd_with_retry"),
        patch.object(kvm.utils, "wait_for_cloud_init"),
        patch.object(kvm.utils, "install_ansible_on_remote"),
        patch.object(kvm.utils, "run_prehard_ansible_remote"),
        patch.object(kvm.utils, "run_hardening_remote") as mock_harden,
        patch.object(kvm.utils, "install_oscap_on_remote"),
        patch.object(kvm.utils, "run_oscap_remote", return_value="<xml/>"),
        patch.object(kvm.utils, "cleanup_instance_history_remote"),
        patch.object(kvm.utils, "run_remote_cmd"),
    ):
        yield {
            "create_overlay": mock_create_overlay,
            "launch_qemu": mock_launch,
            "terminate_qemu": mock_terminate,
            "convert_to_raw": mock_convert,
            "run_hardening_remote": mock_harden,
        }


def test_execute_build_returns_qcow2_artifact(kvm, mocked_build_env, tmp_path):
    result = kvm.execute_build(
        {
            "os": "ubuntu22.04",
            "base_image": "ubuntu22.04",
            "profile_name": "test-profile",
            "profile_version": "1.0.0",
            "profile": "xccdf_profile",
            "datastream": "/path/to/ds.xml",
            "hardening": {"strategy": "ansible-galaxy", "role": "auto", "profile_tier": "cis-l1"},
        }
    )
    assert result["status"] == "success"
    assert result["artifact_type"] == "qcow2"
    assert Path(result["artifact_id"]).name == "image.qcow2"
    mocked_build_env["convert_to_raw"].assert_not_called()

    build_dir = Path(result["artifact_id"]).parent
    assert (build_dir / "metadata.json").is_file()
    assert (build_dir / "image.qcow2.sha256").is_file()


def test_execute_build_converts_to_raw_when_requested(kvm, mocked_build_env):
    result = kvm.execute_build(
        {
            "os": "ubuntu22.04",
            "base_image": "ubuntu22.04",
            "profile_name": "test-profile",
            "profile_version": "1.0.0",
            "hardening": {},
            "output_format": "raw",
        }
    )
    assert result["artifact_type"] == "raw"
    mocked_build_env["convert_to_raw"].assert_called_once()


def test_execute_build_rejects_invalid_output_format(kvm, mocked_build_env):
    with pytest.raises(ValueError, match="output_format"):
        kvm.execute_build({"os": "ubuntu22.04", "output_format": "vmdk"})


def test_execute_build_passes_root_volume_size_to_overlay(kvm, mocked_build_env):
    kvm.execute_build(
        {
            "os": "ubuntu22.04",
            "base_image": "ubuntu22.04",
            "hardening": {},
            "root_volume_size_gb": 30,
        }
    )
    _, kwargs = mocked_build_env["create_overlay"].call_args
    assert kwargs.get("size_gb") == 30 or mocked_build_env["create_overlay"].call_args[0][2] == 30


def test_execute_build_terminates_qemu_on_failure(kvm, mocked_build_env):
    mocked_build_env["run_hardening_remote"].side_effect = RuntimeError("hardening blew up")
    with pytest.raises(RuntimeError, match="hardening blew up"):
        kvm.execute_build({"os": "ubuntu22.04", "base_image": "ubuntu22.04", "hardening": {}})
    mocked_build_env["terminate_qemu"].assert_called_once()


# ---------------------------------------------------------------------------
# Registry / loader contract
# ---------------------------------------------------------------------------


def test_kvm_provider_loaded_as_subprocess():
    from stratum.plugins.loader import load_providers

    providers, _ = load_providers(Path("plugins/providers"))
    assert "kvm" in providers
    assert providers["kvm"].handles_full_lifecycle is True
