# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Final coverage gap tests for non-API modules.

Targets:
  core/llm/anthropic_backend.py  36-37  — ImportError when anthropic not installed
  core/playbook_gen.py           167    — LVM entry with empty lvm_vg → continue
  core/registry.py               163    — non-YAML S3 object key → continue
  core/builder.py                136    — fail_on_findings=True with failures → raise
  core/builder.py                169-170 — teardown exception in finally block
  main.py                        52     — plugin warning logged during startup
  main.py                        62     — S3 bucket source added to registry sources
  plugins/base_provider.py       52     — __repr__ on a provider instance
  api/integrations.py            87-88  — chmod raises OSError → swallowed silently
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ===========================================================================
# core/llm/anthropic_backend.py:36-37 — ImportError when anthropic missing
# ===========================================================================


class TestAnthropicImportError:
    @pytest.mark.anyio
    async def test_agent_turn_raises_runtime_error_when_anthropic_missing(self):
        """Lines 36-37: RuntimeError raised when 'anthropic' is not importable."""
        from statim.core.llm.anthropic_backend import AnthropicBackend

        backend = AnthropicBackend()
        with patch.dict(sys.modules, {"anthropic": None}):
            with pytest.raises(RuntimeError, match="anthropic package not installed"):
                await backend.agent_turn([], [], "", 100, lambda t: None)


# ===========================================================================
# core/playbook_gen.py:167 — LVM entry with empty lvm_vg → continue
# ===========================================================================


class TestPlaybookGenLvmNoVg:
    def test_lvm_tasks_skips_entry_with_no_vg(self):
        """Line 167: entry with mount_type=lvm but empty lvm_vg is skipped."""
        from statim.core.blueprint import MountEntry
        from statim.core.playbook_gen import _lvm_tasks

        mounts = [
            MountEntry(
                device="/dev/sdb",
                mountpoint="/data",
                fstype="xfs",
                mount_type="lvm",
                lvm_vg=None,  # No VG → should continue
            ),
        ]
        tasks = _lvm_tasks(mounts)
        assert tasks == []


# ===========================================================================
# core/registry.py:163 — non-YAML S3 key → continue
# ===========================================================================


class TestRegistryS3SkipsNonYaml:
    def test_sync_s3_skips_non_yaml_keys(self):
        """Line 163: object keys without .yaml/.yml extension are skipped."""
        from statim.core.registry import ProfileRegistry, RegistrySource

        source = RegistrySource("s3", "my-bucket", "Private")
        registry = ProfileRegistry()

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_s3.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": "README.txt"}, {"Key": "notes.md"}]},
        ]

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            result = registry._sync_s3(source)

        assert result == []  # No YAML keys — nothing synced
        mock_s3.get_object.assert_not_called()


# ===========================================================================
# core/builder.py:136 — fail_on_findings=True with scan failures → raise
# ===========================================================================

_PROFILE_YAML = {
    "statim_version": "0.1.0",
    "kind": "ComplianceProfile",
    "metadata": {"name": "builder-gap-test", "version": "1.0.0"},
    "target": {"os": "ubuntu22.04", "provider": "mock", "base_image": "ami-00"},
    "compliance": {
        "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
        "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
        "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
        "fail_on_findings": True,
    },
}


def _make_mock_provider(instance_id="i-gap-test", teardown_raises=False):
    mock_cls = MagicMock()
    mock_cls.handles_full_lifecycle = False
    mock_cls.name = "mock"
    inst = MagicMock()
    inst.provision.return_value = instance_id
    inst.run_ansible.return_value = None
    if teardown_raises:
        inst.teardown.side_effect = RuntimeError("teardown kaboom")
    mock_cls.return_value = inst
    return mock_cls


class TestBuilderGaps:
    @pytest.mark.anyio
    async def test_run_build_fail_on_findings_raises(self):
        """Line 136: RuntimeError raised when scan has failures and fail_on_findings=True."""
        from statim.core.blueprint import ComplianceProfile
        from statim.core.builder import run_build

        profile = ComplianceProfile.model_validate(_PROFILE_YAML)

        mock_cls = _make_mock_provider()

        def _close_coro(coro, *a, **kw):
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        with patch("statim.core.builder.registry") as mock_reg:
            mock_reg.get.return_value = mock_cls
            with patch("statim.core.builder.generate_prehard_playbook", return_value=None):
                with patch("statim.core.builder.oscap_scanner.run_scan", return_value=Path("/tmp/scan.xml")):
                    with patch("statim.openscap.parser.parse_arf", return_value={"rules": [{"result": "fail"}]}):
                        with patch("statim.openscap.parser.RESULT_FAIL", "fail"):
                            with patch("asyncio.create_task", side_effect=_close_coro):
                                job = await run_build(profile, Path("/tmp"))

        assert job.status.value == "failed"
        assert "compliance rule" in (job.error or "")

    @pytest.mark.anyio
    async def test_run_build_teardown_exception_logged(self):
        """Lines 169-170: teardown exception is logged but does not propagate."""
        from statim.core.blueprint import ComplianceProfile
        from statim.core.builder import run_build

        profile = ComplianceProfile.model_validate(
            {**_PROFILE_YAML, "compliance": {**_PROFILE_YAML["compliance"], "fail_on_findings": False}}
        )

        mock_cls = _make_mock_provider(teardown_raises=True)
        # Make run_ansible fail so build fails fast (instance_id already set)
        mock_cls.return_value.run_ansible.side_effect = RuntimeError("ansible failed")

        def _close_coro(coro, *a, **kw):
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        with patch("statim.core.builder.registry") as mock_reg:
            mock_reg.get.return_value = mock_cls
            with patch("statim.core.builder.generate_prehard_playbook", return_value=None):
                with patch("asyncio.create_task", side_effect=_close_coro):
                    job = await run_build(profile, Path("/tmp"))

        assert job.status.value == "failed"
        assert "ansible failed" in (job.error or "")


# ===========================================================================
# main.py:52 — plugin warning logged
# ===========================================================================


class TestMainStartup:
    @pytest.mark.anyio
    async def test_startup_logs_plugin_warnings(self):
        """Line 52: plugin warnings from registry.load are logged."""
        from statim.main import app, lifespan

        with patch("statim.main.registry.load", return_value=["PluginX: missing dependency"]):
            with patch("statim.main.credential_store.load"):
                with patch("statim.core.auditor.load_jobs"):
                    with patch("statim.core.api_keys.load_keys"):
                        with patch("statim.core.notifications.load_webhooks"):
                            with patch("statim.main.init_registry"):
                                async with lifespan(app):
                                    pass

    @pytest.mark.anyio
    async def test_startup_with_s3_bucket_adds_source(self):
        """Line 62: S3 RegistrySource is inserted when blueprint_store_s3_bucket is set."""
        from statim.config import settings
        from statim.main import app, lifespan

        sources_seen = []

        def capture_sources(sources, **kw):
            sources_seen.extend(sources)

        with patch.object(settings, "blueprint_store_s3_bucket", "my-private-bucket"):
            with patch("statim.main.registry.load", return_value=[]):
                with patch("statim.main.credential_store.load"):
                    with patch("statim.core.auditor.load_jobs"):
                        with patch("statim.core.api_keys.load_keys"):
                            with patch("statim.core.notifications.load_webhooks"):
                                with patch("statim.main.init_registry", side_effect=capture_sources):
                                    async with lifespan(app):
                                        pass

        s3_sources = [s for s in sources_seen if s.kind == "s3"]
        assert len(s3_sources) == 1
        assert s3_sources[0].url_or_bucket == "my-private-bucket"


# ===========================================================================
# plugins/base_provider.py:52 — __repr__
# ===========================================================================


class TestBaseProviderRepr:
    def test_repr_returns_provider_name(self):
        """Line 52: __repr__ returns '<Provider name=...>' string."""
        from statim.plugins.subprocess_provider import SubprocessProvider

        class MockProvider(SubprocessProvider):
            name = "mock-repr-test"
            script_path = "mock_script.py"

        p = MockProvider()
        r = repr(p)
        assert "mock-repr-test" in r
        assert "Provider" in r


# ===========================================================================
# api/integrations.py:87-88 — chmod raises OSError → swallowed
# ===========================================================================


class TestCredentialStoreChmod:
    def test_persist_swallows_chmod_oserror(self, tmp_path):
        """Lines 87-88: OSError from chmod(0o600) on credentials file is silently ignored."""
        from statim.api.integrations import CredentialStore

        store = CredentialStore(tmp_path)
        store._store = {"aws": {"access_key": "AKID"}}

        # Patch chmod to raise OSError only for the credentials file
        real_chmod = Path.chmod

        def _fail_chmod(self, mode, *a, **kw):
            if "credentials.enc" in str(self):
                raise OSError("Operation not permitted")
            return real_chmod(self, mode, *a, **kw)

        with patch.object(Path, "chmod", _fail_chmod):
            store._persist()  # Should not raise
