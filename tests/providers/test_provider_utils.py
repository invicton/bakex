# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for plugins/providers/_provider_utils.py — pure Python utilities.

No cloud SDK calls. Everything here is testable without credentials.
"""

from __future__ import annotations

import os
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
        # Ansible Galaxy's real name for this role is the abbreviated
        # "deb12_cis", not "debian12_cis" — see test_lockdown_role_matches_real_galaxy_name.
        role = utils.lockdown_role_for_os("debian12")
        assert "CIS" in role.upper()

    def test_amazon_linux_2023_maps_correctly(self):
        role = utils.lockdown_role_for_os("amazon2023")
        assert "AMAZON" in role.upper()

    def test_unknown_os_raises_value_error(self):
        with pytest.raises(ValueError, match="No ansible-lockdown role"):
            utils.lockdown_role_for_os("archlinux-unknown-xyz")

    def test_role_name_contains_cis(self):
        role = utils.lockdown_role_for_os("ubuntu22.04")
        assert "CIS" in role.upper(), "Lockdown role must contain 'CIS'"

    # Regression: these role identifiers must exactly match Ansible Galaxy's
    # `name` field (verified against
    # https://galaxy.ansible.com/api/v1/roles/?owner__username=ansible-lockdown),
    # which frequently differs from the ansible-lockdown GitHub repo name —
    # `ansible-galaxy install ansible-lockdown.<name>` fails with "role not
    # found" on any mismatch. This previously used repo-name casing (e.g.
    # "UBUNTU22-CIS", "DEBIAN12-CIS") which does not exist on Galaxy at all.
    @pytest.mark.parametrize(
        ("os_name", "expected_role"),
        [
            ("ubuntu22.04", "ubuntu22_cis"),
            ("ubuntu24.04", "ubuntu24_cis"),
            ("ubuntu20.04", "ubuntu20_cis"),
            ("debian12", "deb12_cis"),  # not "debian12_cis" — a real, non-obvious Galaxy quirk
            ("debian11", "debian11_cis"),
            ("rocky9", "rhel9_cis"),
            ("rhel9", "rhel9_cis"),
            ("rocky8", "rhel8_cis"),
            ("rhel8", "rhel8_cis"),
            ("amazon2023", "amazon2023_cis"),
            ("amazon2", "amazon2_cis"),
        ],
    )
    def test_lockdown_role_matches_real_galaxy_name(self, os_name, expected_role):
        assert utils.lockdown_role_for_os(os_name) == expected_role


# ===========================================================================
# tier_extra_vars — profile tier → Ansible extra_vars dict
# ===========================================================================


class TestTierExtraVars:
    """Role name arguments use the real Galaxy name (underscore), e.g.
    "UBUNTU22_CIS" — NOT the GitHub repo name/casing ("UBUNTU22-CIS"), which
    ansible-galaxy install actually rejects with "role not found"."""

    def test_cis_l1_ubuntu22_level1_true(self):
        vars_ = utils.tier_extra_vars("cis-l1", "UBUNTU22_CIS")
        assert vars_.get("ubuntu22cis_level1") is True

    def test_cis_l1_ubuntu22_level2_false(self):
        vars_ = utils.tier_extra_vars("cis-l1", "UBUNTU22_CIS")
        assert vars_.get("ubuntu22cis_level2") is False

    def test_cis_l2_ubuntu22_both_true(self):
        vars_ = utils.tier_extra_vars("cis-l2", "UBUNTU22_CIS")
        assert vars_.get("ubuntu22cis_level1") is True
        assert vars_.get("ubuntu22cis_level2") is True

    def test_cis_l1_rhel9_vars_correct(self):
        vars_ = utils.tier_extra_vars("cis-l1", "RHEL9_CIS")
        assert vars_.get("rhel9cis_level1") is True
        assert vars_.get("rhel9cis_level2") is False

    def test_cis_l2_rhel9_both_true(self):
        vars_ = utils.tier_extra_vars("cis-l2", "RHEL9_CIS")
        assert vars_.get("rhel9cis_level1") is True
        assert vars_.get("rhel9cis_level2") is True

    def test_namespaced_role_stripped(self):
        """ansible-lockdown.UBUNTU22_CIS should resolve same as UBUNTU22_CIS."""
        v1 = utils.tier_extra_vars("cis-l1", "ansible-lockdown.UBUNTU22_CIS")
        v2 = utils.tier_extra_vars("cis-l1", "UBUNTU22_CIS")
        assert v1 == v2

    def test_unknown_role_falls_back_to_generic(self):
        vars_ = utils.tier_extra_vars("cis-l1", "SOME-UNKNOWN-ROLE")
        assert "cis_level1" in vars_, "Generic fallback must use cis_level1"

    def test_custom_tier_returns_empty_dict(self):
        vars_ = utils.tier_extra_vars("custom", "UBUNTU22_CIS")
        assert vars_ == {}

    def test_returns_dict(self):
        result = utils.tier_extra_vars("cis-l1", "RHEL9_CIS")
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


# ===========================================================================
# run_hardening_remote — Galaxy install must pin a version, not "latest"
# ===========================================================================
#
# Regression: several ansible-lockdown repos mix git tag formats ("V1.0.0"
# alongside "1.1.0"), which makes `ansible-galaxy install <role>` (no version)
# fail outright with "Unable to compare role versions ... due to incompatible
# version formats" when it tries to resolve "latest". Discovered by actually
# running a build end-to-end against a local KVM guest.


class TestRunHardeningRemoteVersionPinning:
    def _galaxy_install_cmd(self, mock_run_remote_cmd):
        """Return the `ansible-galaxy install ...` command string from all
        calls made to the mocked run_remote_cmd."""
        for call in mock_run_remote_cmd.call_args_list:
            cmd = call.args[3] if len(call.args) > 3 else call.kwargs.get("command", "")
            if "ansible-galaxy install" in cmd:
                return cmd
        raise AssertionError("no ansible-galaxy install call found")

    def test_auto_role_install_pins_known_version(self, tmp_path):
        with patch("_provider_utils.run_remote_cmd") as mock_run:
            mock_run.return_value = (0, "", "")
            utils.run_hardening_remote(
                "127.0.0.1",
                "ubuntu",
                tmp_path / "key",
                "ubuntu22.04",
                {"strategy": "ansible-galaxy", "role": "auto", "profile_tier": "cis-l1"},
            )
        cmd = self._galaxy_install_cmd(mock_run)
        assert "ansible-lockdown.ubuntu22_cis,3.0.0" in cmd

    def test_explicit_role_override_is_not_auto_pinned(self, tmp_path):
        """A user-specified role/version string must pass through unchanged —
        pinning only applies to BakeX's own auto-resolved roles."""
        with patch("_provider_utils.run_remote_cmd") as mock_run:
            mock_run.return_value = (0, "", "")
            utils.run_hardening_remote(
                "127.0.0.1",
                "ubuntu",
                tmp_path / "key",
                "ubuntu22.04",
                {"strategy": "ansible-galaxy", "role": "ansible-lockdown.ubuntu22_cis,2.0.0", "profile_tier": "cis-l1"},
            )
        cmd = self._galaxy_install_cmd(mock_run)
        assert "ansible-lockdown.ubuntu22_cis,2.0.0" in cmd
        assert ",3.0.0" not in cmd


# ===========================================================================
# install_oscap_on_remote — Debian-family install must not bundle
# nonexistent package names into the same apt-get call
# ===========================================================================
#
# Regression: "ssg-debderived" and "scap-security-guide" (the RHEL/Fedora
# package name) don't exist for Debian/Ubuntu at all. Bundling either into
# `apt-get install openscap-scanner <nonexistent>` failed the *entire*
# install — even on Debian 12 / Ubuntu 24.04+, where openscap-scanner itself
# is a real, installable package. Discovered by running a build end-to-end
# against a local KVM guest.


class TestInstallOscapOnRemote:
    def test_debian_family_installs_openscap_scanner_alone(self, tmp_path):
        with patch("_provider_utils.run_remote_cmd") as mock_run:
            mock_run.return_value = (0, "", "")
            utils.install_oscap_on_remote("127.0.0.1", "ubuntu", tmp_path / "key")
        script = mock_run.call_args[0][3]
        assert "apt-get install -y openscap-scanner 2>&1;" in script
        assert "ssg-debderived" not in script

    def test_rhel_family_still_installs_scap_security_guide(self, tmp_path):
        """scap-security-guide IS the correct real package name for dnf/yum
        (RHEL/Fedora) — only the Debian-family branch was broken."""
        with patch("_provider_utils.run_remote_cmd") as mock_run:
            mock_run.return_value = (0, "", "")
            utils.install_oscap_on_remote("127.0.0.1", "ec2-user", tmp_path / "key")
        script = mock_run.call_args[0][3]
        assert "dnf install -y openscap openscap-scanner scap-security-guide" in script
        assert "yum install -y openscap openscap-scanner scap-security-guide" in script

    def test_no_datastream_arg_skips_content_check(self, tmp_path):
        """Without a datastream path, only the package-install call happens —
        no `test -f` probe, no fallback download attempt."""
        with patch("_provider_utils.run_remote_cmd") as mock_run:
            mock_run.return_value = (0, "", "")
            utils.install_oscap_on_remote("127.0.0.1", "ubuntu", tmp_path / "key")
        assert mock_run.call_count == 1

    def test_datastream_already_present_skips_fallback(self, tmp_path):
        with (
            patch("_provider_utils.run_remote_cmd") as mock_run,
            patch("_provider_utils._ensure_scap_content_cached") as mock_fallback,
        ):
            mock_run.return_value = (0, "", "")  # install script, then `test -f` -> rc 0
            utils.install_oscap_on_remote(
                "127.0.0.1",
                "ubuntu",
                tmp_path / "key",
                datastream="/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            )
        mock_fallback.assert_not_called()

    def test_datastream_missing_triggers_fallback_download_and_upload(self, tmp_path):
        ds_path = "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml"
        local_content = tmp_path / "ssg-ubuntu2204-ds.xml"
        local_content.write_text("<xccdf/>")

        call_log = []

        def fake_run_remote_cmd(host, user, key_path, command, **kwargs):
            call_log.append(command)
            if command.startswith("test -f"):
                return (1, "", "")  # not present
            return (0, "", "")

        with (
            patch("_provider_utils.run_remote_cmd", side_effect=fake_run_remote_cmd),
            patch("_provider_utils._ensure_scap_content_cached", return_value=local_content) as mock_fallback,
            patch("_provider_utils.copy_file_to_remote") as mock_copy,
        ):
            utils.install_oscap_on_remote(
                "127.0.0.1", "ubuntu", tmp_path / "key", os_name="ubuntu22.04", datastream=ds_path
            )

        mock_fallback.assert_called_once_with(ds_path, Path("data/scap-content"))
        # Must copy the local *file* (a real path, not literal file content —
        # datastreams are 10MB+, too big to read into memory as a string twice).
        mock_copy.assert_called_once()
        assert mock_copy.call_args[0][0] == str(local_content)
        assert any(f"mkdir -p {os.path.dirname(ds_path)}" in c for c in call_log)
        assert any("mv " in c and ds_path in c for c in call_log)

    def test_datastream_missing_and_no_fallback_available_does_not_raise(self, tmp_path):
        """Best-effort: if the fallback can't provide content either, log and
        move on — let the actual oscap invocation fail loudly instead."""

        def fake_run_remote_cmd(host, user, key_path, command, **kwargs):
            if command.startswith("test -f"):
                return (1, "", "")
            return (0, "", "")

        with (
            patch("_provider_utils.run_remote_cmd", side_effect=fake_run_remote_cmd),
            patch("_provider_utils._ensure_scap_content_cached", return_value=None),
            patch("_provider_utils.copy_file_to_remote") as mock_copy,
        ):
            utils.install_oscap_on_remote(
                "127.0.0.1", "ubuntu", tmp_path / "key", os_name="ubuntu22.04", datastream="/some/ds.xml"
            )
        mock_copy.assert_not_called()


# ===========================================================================
# _ensure_scap_content_cached — ComplianceAsCode datastream download fallback
# ===========================================================================


class TestEnsureScapContentCached:
    def test_returns_cached_file_without_downloading(self, tmp_path):
        cached = tmp_path / "ssg-ubuntu2204-ds.xml"
        cached.write_text("<xccdf/>")
        with patch("_provider_utils.urllib.request.urlretrieve") as mock_dl:
            result = utils._ensure_scap_content_cached("/some/path/ssg-ubuntu2204-ds.xml", tmp_path)
        assert result == cached
        mock_dl.assert_not_called()

    def test_empty_basename_returns_none(self, tmp_path):
        assert utils._ensure_scap_content_cached("", tmp_path) is None

    def test_downloads_verifies_checksum_and_extracts_member(self, tmp_path):
        import hashlib
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                f"scap-security-guide-{utils._SCAP_CONTENT_VERSION}/ssg-ubuntu2204-ds.xml", "<xccdf>content</xccdf>"
            )
        zip_bytes = buf.getvalue()
        checksum = hashlib.sha512(zip_bytes).hexdigest()

        def fake_urlretrieve(url, dest):
            Path(dest).write_bytes(zip_bytes)

        mock_checksum_resp = MagicMock()
        mock_checksum_resp.__enter__ = MagicMock(return_value=mock_checksum_resp)
        mock_checksum_resp.__exit__ = MagicMock(return_value=False)
        mock_checksum_resp.read.return_value = f"{checksum}  scap-security-guide.zip".encode()

        with (
            patch("_provider_utils.urllib.request.urlretrieve", side_effect=fake_urlretrieve),
            patch("_provider_utils.urllib.request.urlopen", return_value=mock_checksum_resp),
        ):
            result = utils._ensure_scap_content_cached("/some/path/ssg-ubuntu2204-ds.xml", tmp_path)

        assert result is not None
        assert result.read_text() == "<xccdf>content</xccdf>"

    def test_checksum_mismatch_returns_none(self, tmp_path):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(f"scap-security-guide-{utils._SCAP_CONTENT_VERSION}/ssg-ubuntu2204-ds.xml", "<xccdf/>")
        zip_bytes = buf.getvalue()

        def fake_urlretrieve(url, dest):
            Path(dest).write_bytes(zip_bytes)

        mock_checksum_resp = MagicMock()
        mock_checksum_resp.__enter__ = MagicMock(return_value=mock_checksum_resp)
        mock_checksum_resp.__exit__ = MagicMock(return_value=False)
        mock_checksum_resp.read.return_value = b"0" * 128 + b"  scap-security-guide.zip"

        with (
            patch("_provider_utils.urllib.request.urlretrieve", side_effect=fake_urlretrieve),
            patch("_provider_utils.urllib.request.urlopen", return_value=mock_checksum_resp),
        ):
            result = utils._ensure_scap_content_cached("/some/path/ssg-ubuntu2204-ds.xml", tmp_path)

        assert result is None

    def test_missing_member_in_archive_returns_none(self, tmp_path):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(f"scap-security-guide-{utils._SCAP_CONTENT_VERSION}/ssg-rhel9-ds.xml", "<xccdf/>")
        zip_bytes = buf.getvalue()

        def fake_urlretrieve(url, dest):
            Path(dest).write_bytes(zip_bytes)

        with (
            patch("_provider_utils.urllib.request.urlretrieve", side_effect=fake_urlretrieve),
            patch("_provider_utils.urllib.request.urlopen", side_effect=Exception("no checksum")),
        ):
            result = utils._ensure_scap_content_cached("/some/path/ssg-does-not-exist-ds.xml", tmp_path)

        assert result is None


# ===========================================================================
# run_oscap_remote — must raise, not silently return, when no results appear
# ===========================================================================
#
# Regression: a build with the oscap binary or SCAP content missing entirely
# (e.g. Ubuntu 22.04's missing openscap-scanner package) previously appeared
# to "succeed" — the empty result was just logged as a warning and returned
# as if it were a legitimate (if odd) scan outcome.


class TestRunOscapRemote:
    def test_empty_output_raises(self, tmp_path):
        with patch("_provider_utils.run_remote_cmd", return_value=(1, "", "oscap: command not found")):
            with pytest.raises(RuntimeError, match="oscap produced no results"):
                utils.run_oscap_remote("127.0.0.1", "ubuntu", tmp_path / "key", "profile-id", "/some/ds.xml")

    def test_nonempty_output_returns_it(self, tmp_path):
        with patch("_provider_utils.run_remote_cmd", return_value=(2, "<xccdf>results</xccdf>", "")):
            result = utils.run_oscap_remote("127.0.0.1", "ubuntu", tmp_path / "key", "profile-id", "/some/ds.xml")
        assert result == "<xccdf>results</xccdf>"
