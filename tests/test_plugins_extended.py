# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Extended tests for plugin loader and subprocess_provider gaps.

Covers the previously uncovered lines:
  loader.py                  lines 42-58  (entry_points happy/failure paths)
  loader.py                  line  68     (spec is None → skip)
  loader.py                  lines 75-77  (subprocess provider collision warning)
  subprocess_provider.py     lines 39,41,43 (optional profile fields: system/filesystem/users)
  subprocess_provider.py     lines 51-53  (prehard_playbook_yaml path)
  subprocess_provider.py     line  56     (credentials passthrough)
  subprocess_provider.py     lines 158-161 (SubprocessProvider.audit)
  subprocess_provider.py     lines 165-169 (SubprocessProvider.scan_image)
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stratum.plugins.base_provider import BaseProvider, ProviderResult
from stratum.plugins.loader import load_providers
from stratum.plugins.subprocess_provider import (
    _build_params,
    make_subprocess_provider_class,
)

# ---------------------------------------------------------------------------
# Minimal ComplianceProfile factory
# ---------------------------------------------------------------------------


def _make_profile(**overrides):
    from stratum.core.blueprint import ComplianceProfile

    data = {
        "stratum_version": "0.1.0",
        "kind": "ComplianceProfile",
        "metadata": {"name": "test-profile", "version": "1.0.0"},
        "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
        "compliance": {
            "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
            "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
            "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
        },
    }
    data.update(overrides)
    return ComplianceProfile.model_validate(data)


# ===========================================================================
# loader.py — entry_points paths (lines 42-58)
# ===========================================================================


class TestEntryPoints:
    def _make_ep(self, name, cls):
        ep = MagicMock(spec=importlib.metadata.EntryPoint)
        ep.name = name
        ep.load.return_value = cls
        return ep

    def test_entry_point_happy_path_registers_provider(self, tmp_path):
        """A valid entry_point provider is added to the result dict."""

        class EPProvider(BaseProvider):
            name = "ep_provider"

            def provision(self, profile, **kwargs):
                return "i"

            def run_ansible(self, instance_id, profile):
                pass

            def snapshot(self, instance_id, profile):
                return ProviderResult(artifact_id="a", artifact_type="ami")

            def teardown(self, instance_id):
                pass

        ep = self._make_ep("ep_provider", EPProvider)
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            providers, warnings = load_providers(tmp_path)
        assert "ep_provider" in providers

    def test_entry_point_load_failure_collected_as_error(self, tmp_path):
        """When ep.load() raises, the error is collected; strict=True re-raises."""
        ep = MagicMock(spec=importlib.metadata.EntryPoint)
        ep.name = "bad_ep"
        ep.load.side_effect = ImportError("broken plugin")
        with patch("importlib.metadata.entry_points", return_value=[ep]):
            with pytest.raises(RuntimeError, match="Plugin loading failed"):
                load_providers(tmp_path, strict=True)

    def test_entry_points_query_failure_collected_as_error(self, tmp_path):
        """If entry_points() itself raises, the error is collected and re-raised in strict mode."""
        with patch("importlib.metadata.entry_points", side_effect=Exception("metadata error")):
            with pytest.raises(RuntimeError, match="Plugin loading failed"):
                load_providers(tmp_path, strict=True)

    def test_entry_point_collision_emits_warning(self, tmp_path):
        """Two entry_points with the same provider name emit a warning."""

        class EPProviderA(BaseProvider):
            name = "ep_dupe"

            def provision(self, profile, **kwargs):
                return "i"

            def run_ansible(self, instance_id, profile):
                pass

            def snapshot(self, instance_id, profile):
                return ProviderResult(artifact_id="a", artifact_type="ami")

            def teardown(self, instance_id):
                pass

        class EPProviderB(EPProviderA):
            pass

        ep1 = self._make_ep("ep_dupe_1", EPProviderA)
        ep2 = self._make_ep("ep_dupe_2", EPProviderB)
        with patch("importlib.metadata.entry_points", return_value=[ep1, ep2]):
            providers, warnings = load_providers(tmp_path)
        assert "ep_dupe" in providers
        assert any("ep_dupe" in w for w in warnings)


# ===========================================================================
# loader.py — spec is None (line 68)
# ===========================================================================


def test_spec_none_file_is_skipped(tmp_path):
    """If spec_from_file_location returns None, the file is silently skipped."""
    (tmp_path / "nullspec.py").write_text("x = 1")
    with patch("importlib.util.spec_from_file_location", return_value=None):
        providers, warnings = load_providers(tmp_path)
    assert providers == {}


# ===========================================================================
# loader.py — subprocess provider collision (lines 75-77)
# ===========================================================================


def test_subprocess_provider_collision_emits_warning(tmp_path):
    """Two subprocess drop-ins with the same PROVIDER_NAME produce a warning."""
    script_a = "PROVIDER_NAME = 'sp_dupe'\n"
    script_b = "PROVIDER_NAME = 'sp_dupe'\n"
    (tmp_path / "a_sp.py").write_text(script_a)
    (tmp_path / "b_sp.py").write_text(script_b)
    providers, warnings = load_providers(tmp_path, strict=True)
    assert "sp_dupe" in providers
    assert any("sp_dupe" in w for w in warnings)


# ===========================================================================
# subprocess_provider.py — _build_params optional fields
# ===========================================================================


class TestBuildParams:
    def test_params_without_optional_fields(self):
        """Profile with no system/filesystem/users should not include those keys."""
        profile = _make_profile()
        params = _build_params(profile)
        assert "system" not in params
        assert "filesystem" not in params
        assert "users" not in params

    def test_params_with_system(self):
        """system section is serialised into params when present."""
        profile = _make_profile(
            system={
                "timezone": "UTC",
                "locale": "en_US.UTF-8",
            }
        )
        params = _build_params(profile)
        assert "system" in params
        assert params["system"]["timezone"] == "UTC"

    def test_params_with_filesystem(self):
        """Non-empty filesystem list is serialised into params."""
        profile = _make_profile(filesystem=[{"mountpoint": "/tmp", "device": "tmpfs", "fstype": "tmpfs"}])
        params = _build_params(profile)
        assert "filesystem" in params
        assert len(params["filesystem"]) == 1

    def test_params_with_users(self):
        """users section is serialised into params when present."""
        profile = _make_profile(users={"wheel_group": True, "sudo_no_password": False})
        params = _build_params(profile)
        assert "users" in params

    def test_params_with_credentials(self):
        """credentials dict is included when passed."""
        profile = _make_profile()
        creds = {"aws_access_key_id": "AKIA000", "aws_secret_access_key": "secret"}
        params = _build_params(profile, credentials=creds)
        assert params["credentials"] == creds

    def test_params_without_credentials(self):
        """credentials key absent when not passed."""
        profile = _make_profile()
        params = _build_params(profile, credentials=None)
        assert "credentials" not in params

    def test_params_prehard_playbook_included_when_generated(self, tmp_path):
        """prehard_playbook_yaml is populated when playbook_gen returns a path."""
        profile = _make_profile()
        fake_path = tmp_path / "prehard.yml"
        fake_path.write_text("- hosts: all\n  tasks: []")

        with patch("stratum.core.playbook_gen.generate_prehard_playbook", return_value=fake_path):
            params = _build_params(profile)

        assert "prehard_playbook_yaml" in params
        assert "hosts" in params["prehard_playbook_yaml"]

    def test_params_prehard_exception_skipped(self):
        """If playbook_gen raises, _build_params still returns without crashing."""
        profile = _make_profile()
        with patch("stratum.core.playbook_gen.generate_prehard_playbook", side_effect=RuntimeError("boom")):
            params = _build_params(profile)
        assert "prehard_playbook_yaml" not in params


# ===========================================================================
# subprocess_provider.py — SubprocessProvider.audit / scan_image
# ===========================================================================

_DUMMY_SCRIPT = Path("/fake/provider.py")


def _make_sp_class():
    return make_subprocess_provider_class(_DUMMY_SCRIPT, "testsp")


class TestSubprocessProviderMethods:
    def test_audit_calls_execute_audit_rpc(self):
        """audit() calls _call_rpc with method 'execute_audit' and returns result."""
        cls = _make_sp_class()
        provider = cls()
        profile = _make_profile()

        with patch("stratum.plugins.subprocess_provider._call_rpc", return_value={"raw_xml": "<xccdf/>"}) as mock_rpc:
            with patch("stratum.api.integrations.get_credentials", return_value={}):
                result = provider.audit("ami-target-001", profile)

        mock_rpc.assert_called_once()
        call_args = mock_rpc.call_args
        assert call_args.args[1] == "execute_audit"
        assert result == {"raw_xml": "<xccdf/>"}

    def test_audit_passes_target_id_in_params(self):
        """audit() includes target_id in the params dict sent to the RPC."""
        cls = _make_sp_class()
        provider = cls()
        profile = _make_profile()

        with patch("stratum.plugins.subprocess_provider._call_rpc", return_value={}) as mock_rpc:
            with patch("stratum.api.integrations.get_credentials", return_value={}):
                provider.audit("ami-xyz-999", profile)

        _, _, kwargs_or_pos = mock_rpc.call_args.args[0], mock_rpc.call_args.args[1], mock_rpc.call_args.args[2]
        assert kwargs_or_pos.get("target_id") == "ami-xyz-999"

    def test_scan_image_calls_execute_scan_image_rpc(self):
        """scan_image() calls _call_rpc with method 'execute_scan_image'."""
        cls = _make_sp_class()
        provider = cls()

        with patch("stratum.plugins.subprocess_provider._call_rpc", return_value={"raw_xml": "<xccdf/>"}) as mock_rpc:
            with patch("stratum.api.integrations.get_credentials", return_value={}):
                result = provider.scan_image({"image_id": "ami-scan-001"})

        mock_rpc.assert_called_once()
        assert mock_rpc.call_args.args[1] == "execute_scan_image"
        assert result == {"raw_xml": "<xccdf/>"}

    def test_scan_image_merges_credentials(self):
        """scan_image() merges credentials into params when present."""
        cls = _make_sp_class()
        provider = cls()

        creds = {"aws_access_key_id": "AKIA000"}
        with patch("stratum.plugins.subprocess_provider._call_rpc", return_value={}) as mock_rpc:
            with patch("stratum.api.integrations.get_credentials", return_value=creds):
                provider.scan_image({"image_id": "ami-001"})

        sent_params = mock_rpc.call_args.args[2]
        assert sent_params.get("credentials") == creds
