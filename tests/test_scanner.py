# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for stratum/openscap/scanner.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stratum.openscap.scanner import ScanError, _build_command, run_scan


def _make_profile(target_host=None):
    from stratum.core.blueprint import ComplianceProfile

    return ComplianceProfile.model_validate(
        {
            "stratum_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "scan-test", "version": "1.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-0"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
            "controls": {},
        }
    )


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


def test_build_command_localhost(tmp_path):
    profile = _make_profile()
    arf = tmp_path / "results.xml"
    report = tmp_path / "report.html"
    cmd = _build_command(profile, None, "root", arf, report)
    assert cmd[0] == "oscap"
    assert "xccdf" in cmd
    assert "eval" in cmd
    assert str(arf) in cmd
    # No SSH option for localhost
    assert not any("ssh" in arg.lower() for arg in cmd[:3])


def test_build_command_remote_host(tmp_path):
    profile = _make_profile()
    arf = tmp_path / "results.xml"
    report = tmp_path / "report.html"
    cmd = _build_command(profile, "10.0.0.5", "ec2-user", arf, report)
    assert "ssh://ec2-user@10.0.0.5" in cmd
    assert "--ssh-option=StrictHostKeyChecking=no" in cmd


def test_build_command_contains_benchmark(tmp_path):
    profile = _make_profile()
    arf = tmp_path / "results.xml"
    report = tmp_path / "report.html"
    cmd = _build_command(profile, None, "root", arf, report)
    assert "--benchmark-id" in cmd
    assert profile.compliance.benchmark in cmd


def test_build_command_contains_datastream(tmp_path):
    profile = _make_profile()
    arf = tmp_path / "results.xml"
    report = tmp_path / "report.html"
    cmd = _build_command(profile, None, "root", arf, report)
    assert profile.compliance.datastream in cmd


# ---------------------------------------------------------------------------
# run_scan
# ---------------------------------------------------------------------------


def test_run_scan_exit_0_returns_arf_path(tmp_path):
    profile = _make_profile()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        arf = run_scan(profile, output_dir=tmp_path)
    assert arf == tmp_path / "results-arf.xml"


def test_run_scan_exit_2_returns_arf_path(tmp_path):
    """Exit code 2 means findings but not a fatal error."""
    profile = _make_profile()
    mock_result = MagicMock()
    mock_result.returncode = 2
    mock_result.stdout = ""
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        arf = run_scan(profile, output_dir=tmp_path)
    assert arf.name == "results-arf.xml"


def test_run_scan_exit_other_raises_scan_error(tmp_path):
    """Exit code other than 0/2 should raise ScanError."""
    profile = _make_profile()
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "oscap: not found"
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(ScanError, match="oscap exited with code 1"):
            run_scan(profile, output_dir=tmp_path)


def test_run_scan_no_output_dir_creates_temp():
    """When output_dir is None, a temp dir is created."""
    profile = _make_profile()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        arf = run_scan(profile, output_dir=None)
    assert "stratum-scan-" in str(arf.parent)


def test_run_scan_remote_host_passes_to_command(tmp_path):
    """When target_host is provided, SSH args appear in the command."""
    profile = _make_profile()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result) as mock_sub:
        run_scan(profile, target_host="192.168.1.10", ssh_user="ubuntu", output_dir=tmp_path)
    cmd = mock_sub.call_args[0][0]
    assert any("192.168.1.10" in arg for arg in cmd)
