# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for plugins/providers/_provider_utils.py — pure Python utilities.

No cloud SDK calls. Everything here is testable without credentials.
"""

from __future__ import annotations

import subprocess

# Import the shared utils directly from the provider directory
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "plugins" / "providers"))
import _provider_utils as utils

# ===========================================================================
# default_ssh_user — OS → SSH username mapping
# ===========================================================================


class TestDefaultSshUser:
    def test_ubuntu_returns_ubuntu(self):
        assert utils.default_ssh_user("ubuntu") == "ubuntu"

    def test_ubuntu_with_version_suffix(self):
        assert utils.default_ssh_user("ubuntu22.04") == "ubuntu"

    def test_debian_returns_admin(self):
        assert utils.default_ssh_user("debian") == "admin"

    def test_rocky_returns_rocky(self):
        assert utils.default_ssh_user("rocky") == "rocky"

    def test_rhel_returns_ec2_user(self):
        assert utils.default_ssh_user("rhel9") == "ec2-user"

    def test_amazon_returns_ec2_user(self):
        assert utils.default_ssh_user("amazon") == "ec2-user"

    def test_centos_returns_centos(self):
        assert utils.default_ssh_user("centos") == "centos"

    def test_unknown_os_falls_back_to_root(self):
        assert utils.default_ssh_user("archlinux") == "root"

    def test_case_insensitive_lookup(self):
        assert utils.default_ssh_user("UBUNTU") == "ubuntu"

    def test_empty_string_falls_back_to_root(self):
        assert utils.default_ssh_user("") == "root"


# ===========================================================================
# lockdown_role_for_os — OS → Ansible-Lockdown Galaxy role
# ===========================================================================


class TestLockdownRoleForOs:
    def test_ubuntu22_returns_cis_role(self):
        role = utils.lockdown_role_for_os("ubuntu22.04")
        assert "UBUNTU22" in role.upper() or "CIS" in role.upper()

    def test_ubuntu24_returns_cis_role(self):
        role = utils.lockdown_role_for_os("ubuntu24.04")
        assert "UBUNTU24" in role.upper() or "CIS" in role.upper()

    def test_rocky9_returns_rhel9_role(self):
        role = utils.lockdown_role_for_os("rocky9")
        assert "RHEL9" in role.upper()

    def test_rhel9_returns_rhel9_role(self):
        assert utils.lockdown_role_for_os("rhel9") == utils.lockdown_role_for_os("rocky9")

    def test_rhel8_maps_to_rhel8_role(self):
        role = utils.lockdown_role_for_os("rhel8")
        assert "RHEL8" in role.upper()

    def test_debian12_returns_debian_role(self):
        role = utils.lockdown_role_for_os("debian12")
        assert "DEBIAN" in role.upper()

    def test_amazon_linux_2023_maps_correctly(self):
        role = utils.lockdown_role_for_os("amazon2023")
        assert "AMAZON" in role.upper()

    def test_unknown_os_raises_value_error(self):
        with pytest.raises(ValueError, match="No ansible-lockdown role"):
            utils.lockdown_role_for_os("archlinux-unknown-xyz")

    def test_role_name_contains_cis(self):
        role = utils.lockdown_role_for_os("ubuntu22.04")
        assert "CIS" in role.upper(), "Lockdown role must contain 'CIS'"


# ===========================================================================
# tier_extra_vars — profile tier → Ansible extra_vars dict
# ===========================================================================


class TestTierExtraVars:
    def test_cis_l1_ubuntu22_level1_true(self):
        vars_ = utils.tier_extra_vars("cis-l1", "UBUNTU22-CIS")
        assert vars_.get("ubuntu22cis_level1") is True

    def test_cis_l1_ubuntu22_level2_false(self):
        vars_ = utils.tier_extra_vars("cis-l1", "UBUNTU22-CIS")
        assert vars_.get("ubuntu22cis_level2") is False

    def test_cis_l2_ubuntu22_both_true(self):
        vars_ = utils.tier_extra_vars("cis-l2", "UBUNTU22-CIS")
        assert vars_.get("ubuntu22cis_level1") is True
        assert vars_.get("ubuntu22cis_level2") is True

    def test_cis_l1_rhel9_vars_correct(self):
        vars_ = utils.tier_extra_vars("cis-l1", "RHEL9-CIS")
        assert vars_.get("rhel9cis_level1") is True
        assert vars_.get("rhel9cis_level2") is False

    def test_cis_l2_rhel9_both_true(self):
        vars_ = utils.tier_extra_vars("cis-l2", "RHEL9-CIS")
        assert vars_.get("rhel9cis_level1") is True
        assert vars_.get("rhel9cis_level2") is True

    def test_namespaced_role_stripped(self):
        """ansible-lockdown.UBUNTU22-CIS should resolve same as UBUNTU22-CIS."""
        v1 = utils.tier_extra_vars("cis-l1", "ansible-lockdown.UBUNTU22-CIS")
        v2 = utils.tier_extra_vars("cis-l1", "UBUNTU22-CIS")
        assert v1 == v2

    def test_unknown_role_falls_back_to_generic(self):
        vars_ = utils.tier_extra_vars("cis-l1", "SOME-UNKNOWN-ROLE")
        assert "cis_level1" in vars_, "Generic fallback must use cis_level1"

    def test_custom_tier_returns_empty_dict(self):
        vars_ = utils.tier_extra_vars("custom", "UBUNTU22-CIS")
        assert vars_ == {}

    def test_returns_dict(self):
        result = utils.tier_extra_vars("cis-l1", "RHEL9-CIS")
        assert isinstance(result, dict)


# ===========================================================================
# wait_for_ssh — polls until TCP port opens or times out
# ===========================================================================


class TestWaitForSsh:
    def test_success_on_first_attempt(self):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=None)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("socket.create_connection", return_value=mock_conn):
            utils.wait_for_ssh("192.168.1.1", port=22, timeout=30, interval=1)
            # No exception → success

    def test_timeout_raises(self):
        with patch("socket.create_connection", side_effect=OSError("refused")):
            with patch("time.sleep"):  # skip actual sleep
                with pytest.raises(TimeoutError, match="did not open"):
                    utils.wait_for_ssh("192.168.1.1", port=22, timeout=1, interval=1)

    def test_succeeds_after_retry(self):
        """Fails twice, then succeeds."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=None)
        mock_conn.__exit__ = MagicMock(return_value=False)

        attempt = {"count": 0}

        def flaky_connect(addr, timeout):
            attempt["count"] += 1
            if attempt["count"] < 3:
                raise OSError("not yet")
            return mock_conn

        with patch("socket.create_connection", side_effect=flaky_connect):
            with patch("time.sleep"):
                with patch("time.time", side_effect=[0, 1, 2, 3, 999]):
                    utils.wait_for_ssh("192.168.1.1", timeout=100, interval=1)

        assert attempt["count"] == 3


# ===========================================================================
# run_remote_cmd — SSH command execution
# ===========================================================================


class TestRunRemoteCmd:
    def _make_proc(self, returncode=0, stdout="output", stderr=""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_success_returns_tuple(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        with patch("subprocess.run", return_value=self._make_proc(0, "hello", "")):
            rc, out, err = utils.run_remote_cmd("host", "user", key, "echo hello")
        assert rc == 0
        assert out == "hello"

    def test_non_zero_exit_raises_runtime_error(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        with patch("subprocess.run", return_value=self._make_proc(1, "", "Permission denied")):
            with pytest.raises(RuntimeError, match="Remote command failed"):
                utils.run_remote_cmd("host", "user", key, "sudo cmd", check=True)

    def test_exit_code_2_allowed_for_oscap(self, tmp_path):
        """oscap exits 2 when findings exist — must not raise."""
        key = tmp_path / "key"
        key.write_text("fake-key")
        with patch("subprocess.run", return_value=self._make_proc(2, "<xml/>", "")):
            rc, out, _ = utils.run_remote_cmd("host", "user", key, "oscap eval ...", check=True)
        assert rc == 2
        assert "<xml/>" in out

    def test_check_false_does_not_raise_on_nonzero(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        with patch("subprocess.run", return_value=self._make_proc(1, "", "err")):
            rc, _, _ = utils.run_remote_cmd("host", "user", key, "cmd", check=False)
        assert rc == 1

    def test_ssh_options_in_command(self, tmp_path):
        key = tmp_path / "key"
        key.write_text("fake-key")
        with patch("subprocess.run", return_value=self._make_proc()) as mock_run:
            utils.run_remote_cmd("myhost", "ubuntu", key, "uptime")
        cmd = mock_run.call_args[0][0]
        assert "ssh" in cmd[0]
        assert "ubuntu@myhost" in cmd
        assert str(key) in cmd


# ===========================================================================
# generate_ssh_keypair — creates RSA-4096 key pair
# ===========================================================================


class TestGenerateSshKeypair:
    def test_returns_path_and_pubkey(self, tmp_path):
        """Requires ssh-keygen to be available on the test runner."""
        try:
            key_path, pubkey = utils.generate_ssh_keypair(tmp_path)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("ssh-keygen not available")

        assert key_path.exists()
        assert "ssh-rsa" in pubkey or "ecdsa" in pubkey or "ed25519" in pubkey

    def test_private_key_permissions_are_600(self, tmp_path):
        try:
            key_path, _ = utils.generate_ssh_keypair(tmp_path)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("ssh-keygen not available")
        mode = oct(key_path.stat().st_mode)
        assert mode.endswith("600"), f"Private key must be 0600, got {mode}"
