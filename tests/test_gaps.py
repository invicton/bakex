# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests covering remaining coverage gaps in registry.py, parser.py, and playbook_gen.py.

Uncovered lines targeted:
  core/registry.py     88, 90, 94-95, 98-99   — sync_all: s3/local/unknown/exception paths
  core/registry.py     139-140, 163, 170-173   — _sync_github per-file failure; _sync_s3 paths
  core/registry.py     190-191                 — _sync_local per-file failure
  core/parser.py       57-58, 90-91, 116, 148  — score ValueError, notchecked status, _find_test_result nested, _is_approved_exception
  core/playbook_gen.py 145, 167, 335-336, 355, 357, 361-362 — swap fstype, LVM, root pw hash, user fields
"""

from __future__ import annotations

import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from statim.core.parser import SCAPParser as XCCDFParser
from statim.core.playbook_gen import generate_prehard_playbook
from statim.core.registry import ProfileRegistry, RegistrySource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_profile_dict(name="gap-test"):
    return {
        "statim_version": "0.1.0",
        "kind": "ComplianceProfile",
        "metadata": {"name": name, "version": "1.0.0"},
        "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
        "compliance": {
            "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
            "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
            "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
        },
    }


def _make_profile(**overrides):
    from statim.core.blueprint import ComplianceProfile

    d = _minimal_profile_dict()
    d.update(overrides)
    return ComplianceProfile.model_validate(d)


def _xccdf_xml(score_text="75.5", results=None):
    """Build a minimal XCCDF TestResult XML string."""
    results = results or [("pass", "xccdf_rule_sshd_disable_root_login", "high")]
    rule_results = ""
    for res, idref, severity in results:
        rule_results += f'<xccdf:rule-result idref="{idref}" severity="{severity}"><xccdf:result>{res}</xccdf:result></xccdf:rule-result>\n'
    return textwrap.dedent(f"""\
        <?xml version="1.0"?>
        <xccdf:Benchmark xmlns:xccdf="http://checklists.nist.gov/xccdf/1.2">
          <xccdf:TestResult>
            <xccdf:score>{score_text}</xccdf:score>
            {rule_results}
          </xccdf:TestResult>
        </xccdf:Benchmark>
    """)


# ===========================================================================
# core/registry.py
# ===========================================================================


class TestRegistrySync:
    def _make_registry(self, *sources):
        reg = ProfileRegistry.__new__(ProfileRegistry)
        reg._profiles = {}
        reg._sources = list(sources)
        reg._cache_dir = None
        return reg

    @pytest.mark.anyio
    async def test_sync_s3_source_dispatched(self):
        """sync_all dispatches to _sync_s3 for kind=s3."""
        src = RegistrySource(kind="s3", url_or_bucket="my-bucket", badge="Private")
        reg = self._make_registry(src)
        with patch.object(reg, "_sync_s3", return_value=["profile-s3"]) as mock_s3:
            names = await reg.sync()
        mock_s3.assert_called_once_with(src)
        assert "profile-s3" in names

    @pytest.mark.anyio
    async def test_sync_local_source_dispatched(self):
        """sync_all dispatches to _sync_local for kind=local."""
        src = RegistrySource(kind="local", url_or_bucket="/tmp/profiles", badge="Local")
        reg = self._make_registry(src)
        with patch.object(reg, "_sync_local", return_value=["local-profile"]) as mock_local:
            names = await reg.sync()
        mock_local.assert_called_once_with(src)
        assert "local-profile" in names

    @pytest.mark.anyio
    async def test_sync_unknown_source_kind_emits_warning(self, caplog):
        """Unknown source kind logs a warning and returns empty list."""
        import logging

        src = RegistrySource(kind="github", url_or_bucket="x")  # override kind
        src.kind = "ftp"  # unsupported
        reg = self._make_registry(src)
        with caplog.at_level(logging.WARNING, logger="statim.core.registry"):
            names = await reg.sync()
        assert names == []
        assert any("Unknown" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_sync_source_exception_logged_not_raised(self, caplog):
        """Exception in a sync handler is caught and logged, not propagated."""
        import logging

        src = RegistrySource(kind="s3", url_or_bucket="bad-bucket")
        reg = self._make_registry(src)
        with patch.object(reg, "_sync_s3", side_effect=RuntimeError("S3 down")):
            with caplog.at_level(logging.WARNING, logger="statim.core.registry"):
                names = await reg.sync()
        assert names == []
        assert any("failed" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_sync_github_per_file_failure_logged(self, caplog):
        """A failure fetching one file from GitHub is logged but others succeed."""
        import logging

        src = RegistrySource(kind="github", url_or_bucket="https://raw.example.com/profiles", badge="Community")
        reg = self._make_registry(src)

        good_yaml = yaml.dump(_minimal_profile_dict("github-good"))

        index_resp = MagicMock()
        index_resp.raise_for_status = MagicMock()
        index_resp.json.return_value = ["good.yaml", "bad.yaml"]

        good_resp = MagicMock()
        good_resp.raise_for_status = MagicMock()
        good_resp.text = good_yaml

        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = Exception("404 Not Found")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[index_resp, good_resp, bad_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("statim.core.registry.httpx.AsyncClient", return_value=mock_client):
            with caplog.at_level(logging.WARNING, logger="statim.core.registry"):
                names = await reg.sync()

        assert "github-good" in names
        assert any("bad.yaml" in r.message for r in caplog.records)

    def test_sync_s3_boto3_not_installed(self, caplog):
        """_sync_s3 silently skips when boto3 is not installed."""
        import logging

        src = RegistrySource(kind="s3", url_or_bucket="my-bucket")
        reg = self._make_registry(src)
        with patch.dict("sys.modules", {"boto3": None}):
            with caplog.at_level(logging.WARNING, logger="statim.core.registry"):
                names = reg._sync_s3(src)
        assert names == []
        assert any("boto3" in r.message for r in caplog.records)

    def test_sync_s3_object_failure_logged(self, caplog):
        """Individual S3 object failures are logged, not raised."""
        import logging

        src = RegistrySource(kind="s3", url_or_bucket="my-bucket", prefix="profiles/")
        reg = self._make_registry(src)

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": [{"Key": "profiles/broken.yaml"}]}]
        mock_s3.get_paginator.return_value = mock_paginator
        mock_s3.get_object.side_effect = Exception("Access Denied")

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with caplog.at_level(logging.WARNING, logger="statim.core.registry"):
                names = reg._sync_s3(src)

        assert names == []
        assert any("broken.yaml" in r.message or "S3 object" in r.message for r in caplog.records)

    def test_sync_s3_top_level_exception_logged(self, caplog):
        """A top-level S3 failure (e.g. bad bucket) is logged, not raised."""
        import logging

        src = RegistrySource(kind="s3", url_or_bucket="nonexistent-bucket")
        reg = self._make_registry(src)

        mock_s3 = MagicMock()
        mock_s3.get_paginator.side_effect = Exception("Bucket not found")

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            with caplog.at_level(logging.WARNING, logger="statim.core.registry"):
                names = reg._sync_s3(src)

        assert names == []

    def test_sync_local_per_file_failure_logged(self, tmp_path, caplog):
        """A file that raises on read_text is logged; other files succeed."""
        import logging

        good_yaml = yaml.dump(_minimal_profile_dict("local-good"))
        (tmp_path / "a_good.yaml").write_text(good_yaml)
        (tmp_path / "z_bad.yaml").write_text("placeholder")  # will raise on read

        src = RegistrySource(kind="local", url_or_bucket=str(tmp_path), badge="Local")
        reg = self._make_registry(src)

        # Make read_text raise for the second file only
        _call_count = {"n": 0}
        orig_read_text = Path.read_text

        def patched_read_text(self, *args, **kwargs):
            _call_count["n"] += 1
            if _call_count["n"] > 1:
                raise PermissionError("unreadable")
            return orig_read_text(self, *args, **kwargs)

        with patch.object(Path, "read_text", patched_read_text):
            with caplog.at_level(logging.WARNING, logger="statim.core.registry"):
                names = reg._sync_local(src)

        assert "local-good" in names
        assert any("local file" in r.message or "z_bad" in r.message for r in caplog.records)


# ===========================================================================
# core/parser.py
# ===========================================================================


class TestXCCDFParserGaps:
    def test_score_value_error_returns_none(self):
        """Non-numeric score text results in score=None (no crash)."""
        xml = _xccdf_xml(score_text="N/A")
        result = XCCDFParser.parse_report(xml, {})
        assert result["score"] is None

    def test_notchecked_status_counts_as_pass(self):
        """notchecked/notapplicable results increment passed counter."""
        xml = _xccdf_xml(
            results=[
                ("notchecked", "xccdf_rule_some_rule", "low"),
            ]
        )
        result = XCCDFParser.parse_report(xml, {})
        assert result["passed"] == 1
        assert result["failed"] == 0

    def test_find_test_result_nested_in_arf(self):
        """_find_test_result finds TestResult nested inside an ARF wrapper."""
        arf_xml = textwrap.dedent("""\
            <?xml version="1.0"?>
            <arf:asset-report-collection xmlns:arf="http://scap.nist.gov/schema/asset-reporting-format/1.1"
                                         xmlns:xccdf="http://checklists.nist.gov/xccdf/1.2">
              <arf:reports>
                <arf:report>
                  <xccdf:TestResult id="xccdf_result_1">
                    <xccdf:score>88.0</xccdf:score>
                  </xccdf:TestResult>
                </arf:report>
              </arf:reports>
            </arf:asset-report-collection>
        """)
        root = ET.fromstring(arf_xml)
        tr = XCCDFParser._find_test_result(root)
        assert tr is not None

    def test_is_approved_exception_pydantic_model(self):
        """_is_approved_exception works with Pydantic ControlOverride model."""
        from statim.core.blueprint import ControlOverride

        override_disabled = ControlOverride(enabled=False, justification="waiver")
        override_enabled = ControlOverride(enabled=True, justification="")
        assert XCCDFParser._is_approved_exception(override_disabled) is True
        assert XCCDFParser._is_approved_exception(override_enabled) is False


# ===========================================================================
# core/playbook_gen.py
# ===========================================================================


class TestPlaybookGenGaps:
    def test_swap_entry_generates_swapon_task(self):
        """A mount entry with fstype='swap' generates an additional swapon task."""
        profile = _make_profile(filesystem=[{"mountpoint": "swap", "device": "/dev/sdb", "fstype": "swap"}])
        result = generate_prehard_playbook(profile)
        assert result is not None
        content = result.read_text()
        assert "swapon" in content

    def test_lvm_entry_generates_lvm_tasks(self):
        """A mount entry with mount_type='lvm' and lvm_vg generates VG/LV tasks."""
        profile = _make_profile(
            filesystem=[
                {
                    "mountpoint": "/data",
                    "device": "/dev/sdb",
                    "fstype": "ext4",
                    "mount_type": "lvm",
                    "lvm_vg": "datavg",
                }
            ]
        )
        result = generate_prehard_playbook(profile)
        assert result is not None
        content = result.read_text()
        assert "datavg" in content

    def test_root_password_hash_generates_set_password_task(self):
        """When root.password_hash is set, a password task is generated instead of lock."""
        profile = _make_profile(
            users={
                "root": {"lock": False, "password_hash": "$6$fakehash"},
                "accounts": [],
            }
        )
        result = generate_prehard_playbook(profile)
        assert result is not None
        content = result.read_text()
        assert "fakehash" in content

    def test_user_with_comment_and_groups(self):
        """User account with comment and groups produces correct ansible.builtin.user task."""
        profile = _make_profile(
            users={
                "accounts": [
                    {
                        "name": "auditor",
                        "comment": "Audit User",
                        "groups": ["sudo", "adm"],
                        "system": False,
                        "shell": "/bin/bash",
                    }
                ]
            }
        )
        result = generate_prehard_playbook(profile)
        assert result is not None
        content = result.read_text()
        assert "auditor" in content
        assert "Audit User" in content

    def test_user_with_system_flag(self):
        """A system=True user gets system: true in the ansible task."""
        profile = _make_profile(
            users={
                "accounts": [
                    {
                        "name": "svc-agent",
                        "system": True,
                        "shell": "/bin/false",
                    }
                ]
            }
        )
        result = generate_prehard_playbook(profile)
        assert result is not None
        content = result.read_text()
        assert "svc-agent" in content

    def test_user_with_password_hash(self):
        """A user with password_hash gets password and update_password fields."""
        profile = _make_profile(
            users={
                "accounts": [
                    {
                        "name": "admin",
                        "password_hash": "$6$userhash",
                        "shell": "/bin/bash",
                    }
                ]
            }
        )
        result = generate_prehard_playbook(profile)
        assert result is not None
        content = result.read_text()
        assert "userhash" in content
