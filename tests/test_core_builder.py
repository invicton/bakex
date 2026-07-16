# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""core/builder.py unit tests — build orchestration with mocked providers."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest

import statim.core.builder as builder_mod
from statim.core.builder import BuildJob, BuildStatus, get_job, list_jobs, run_build
from statim.plugins.base_provider import ProviderResult


@pytest.fixture(autouse=True)
def _clean_jobs():
    builder_mod._jobs.clear()
    yield
    builder_mod._jobs.clear()


def _make_profile(provider="aws", os_="ubuntu22.04"):
    from statim.core.blueprint import ComplianceProfile

    return ComplianceProfile.model_validate(
        {
            "statim_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "build-test", "version": "1.0"},
            "target": {"os": os_, "provider": provider, "base_image": "ami-00000000"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
            "controls": {},
        }
    )


def _mock_subprocess_provider_cls(artifact_id="ami-99999999"):
    """Returns a mock provider class with handles_full_lifecycle=True."""
    provider = MagicMock()
    provider.provision.return_value = "i-stub"
    provider.run_ansible.return_value = None
    provider.snapshot.return_value = ProviderResult(artifact_id=artifact_id, artifact_type="ami")
    provider.teardown.return_value = None

    cls = MagicMock()
    cls.handles_full_lifecycle = True
    cls.name = "aws"
    cls.return_value = provider
    return cls, provider


def _mock_local_provider_cls(instance_id="local-vm-1", artifact_id="snapshot-001"):
    """Returns a mock provider class with handles_full_lifecycle=False."""
    provider = MagicMock()
    provider.provision.return_value = instance_id
    provider.run_ansible.return_value = None
    provider.snapshot.return_value = ProviderResult(artifact_id=artifact_id, artifact_type="qcow2")
    provider.teardown.return_value = None

    cls = MagicMock()
    cls.handles_full_lifecycle = False
    cls.name = "local"
    cls.return_value = provider
    return cls, provider


# ---------------------------------------------------------------------------
# BuildJob dataclass
# ---------------------------------------------------------------------------


def test_build_job_default_status():
    job = BuildJob()
    assert job.status == BuildStatus.PENDING


def test_build_job_update_changes_status():
    job = BuildJob()
    job._update(BuildStatus.HARDENING, "hardening started")
    assert job.status == BuildStatus.HARDENING
    assert len(job.log) == 1
    assert "hardening started" in job.log[0]


def test_build_job_log_accumulates():
    job = BuildJob()
    job._update(BuildStatus.PROVISIONING, "provisioning")
    job._update(BuildStatus.HARDENING, "hardening")
    assert len(job.log) == 2


# ---------------------------------------------------------------------------
# get_job / list_jobs
# ---------------------------------------------------------------------------


def test_get_job_returns_job():
    job = BuildJob()
    builder_mod._jobs[job.id] = job
    assert get_job(job.id) is job


def test_get_job_nonexistent_returns_none():
    assert get_job("no-such-id") is None


def test_list_jobs_sorted_newest_first():
    from datetime import datetime

    j1 = BuildJob(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    j2 = BuildJob(created_at=datetime(2026, 1, 3, tzinfo=UTC))
    builder_mod._jobs[j1.id] = j1
    builder_mod._jobs[j2.id] = j2
    result = list_jobs()
    assert result[0].id == j2.id


def test_list_jobs_empty():
    assert list_jobs() == []


# ---------------------------------------------------------------------------
# run_build — subprocess provider (handles_full_lifecycle=True)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_build_subprocess_complete(tmp_path):
    profile = _make_profile(provider="aws")
    cls, provider = _mock_subprocess_provider_cls()

    with patch.object(builder_mod.registry, "get", return_value=cls):
        job = await run_build(profile, tmp_path)

    assert job.status == BuildStatus.COMPLETE
    assert job.result.artifact_id == "ami-99999999"
    provider.provision.assert_called_once()
    provider.snapshot.assert_called_once()
    provider.teardown.assert_called_once()


@pytest.mark.anyio
async def test_run_build_subprocess_teardown_on_failure(tmp_path):
    profile = _make_profile(provider="aws")
    cls, provider = _mock_subprocess_provider_cls()
    provider.snapshot.side_effect = RuntimeError("snapshot failed")

    with patch.object(builder_mod.registry, "get", return_value=cls):
        job = await run_build(profile, tmp_path)

    assert job.status == BuildStatus.FAILED
    assert "snapshot failed" in job.error
    provider.teardown.assert_called_once()


@pytest.mark.anyio
async def test_run_build_subprocess_uses_existing_job(tmp_path):
    profile = _make_profile(provider="aws")
    cls, provider = _mock_subprocess_provider_cls()
    existing_job = BuildJob(profile_name="build-test", provider_name="aws")
    builder_mod._jobs[existing_job.id] = existing_job

    with patch.object(builder_mod.registry, "get", return_value=cls):
        job = await run_build(profile, tmp_path, job=existing_job)

    assert job is existing_job
    assert job.status == BuildStatus.COMPLETE


# ---------------------------------------------------------------------------
# run_build — class-based provider (handles_full_lifecycle=False)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_build_local_complete(tmp_path):
    profile = _make_profile(provider="local")
    cls, provider = _mock_local_provider_cls()

    fake_arf = tmp_path / "scan.xml"
    fake_arf.write_text("<arf/>")

    with patch.object(builder_mod.registry, "get", return_value=cls):
        with patch("statim.core.builder.generate_prehard_playbook", return_value=None):
            with patch("statim.core.builder.oscap_scanner.run_scan", return_value=fake_arf):
                with patch("statim.openscap.parser.parse_arf", return_value={"rules": []}):
                    job = await run_build(profile, tmp_path)

    assert job.status == BuildStatus.COMPLETE
    assert job.arf_path == fake_arf
    provider.provision.assert_called_once()
    provider.run_ansible.assert_called_once()
    provider.snapshot.assert_called_once()
    provider.teardown.assert_called_once()


@pytest.mark.anyio
async def test_run_build_local_runs_prehard_playbook(tmp_path):
    profile = _make_profile(provider="local")
    cls, provider = _mock_local_provider_cls()

    fake_arf = tmp_path / "scan.xml"
    fake_arf.write_text("<arf/>")
    fake_playbook = tmp_path / "prehard.yaml"
    fake_playbook.write_text("---")

    with patch.object(builder_mod.registry, "get", return_value=cls):
        with patch("statim.core.builder.generate_prehard_playbook", return_value=fake_playbook):
            with patch("statim.core.builder.oscap_scanner.run_scan", return_value=fake_arf):
                with patch("statim.core.builder._run_prehard_ansible") as mock_prehard:
                    with patch("statim.openscap.parser.parse_arf", return_value={"rules": []}):
                        job = await run_build(profile, tmp_path)

    mock_prehard.assert_called_once_with(fake_playbook, "local-vm-1")
    assert job.status == BuildStatus.COMPLETE


@pytest.mark.anyio
async def test_run_build_local_provision_failure_marks_failed(tmp_path):
    profile = _make_profile(provider="local")
    cls, provider = _mock_local_provider_cls()
    provider.provision.side_effect = RuntimeError("provisioning failed")

    with patch.object(builder_mod.registry, "get", return_value=cls):
        with patch("statim.core.builder.generate_prehard_playbook", return_value=None):
            job = await run_build(profile, tmp_path)

    assert job.status == BuildStatus.FAILED
    assert "provisioning failed" in job.error


@pytest.mark.anyio
async def test_run_build_local_ansible_failure_marks_failed(tmp_path):
    profile = _make_profile(provider="local")
    cls, provider = _mock_local_provider_cls()
    provider.run_ansible.side_effect = RuntimeError("ansible error")

    fake_arf = tmp_path / "scan.xml"
    fake_arf.write_text("<arf/>")

    with patch.object(builder_mod.registry, "get", return_value=cls):
        with patch("statim.core.builder.generate_prehard_playbook", return_value=None):
            job = await run_build(profile, tmp_path)

    assert job.status == BuildStatus.FAILED
    assert "ansible error" in job.error


# ---------------------------------------------------------------------------
# _run_prehard_ansible
# ---------------------------------------------------------------------------


def test_run_prehard_ansible_success(tmp_path):
    playbook = tmp_path / "play.yaml"
    playbook.write_text("---")
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_sub:
        builder_mod._run_prehard_ansible(playbook, "10.0.0.1")
    mock_sub.assert_called_once()
    cmd = mock_sub.call_args[0][0]
    assert "ansible-playbook" in cmd


def test_run_prehard_ansible_nonzero_raises(tmp_path):
    playbook = tmp_path / "play.yaml"
    playbook.write_text("---")
    mock_result = MagicMock()
    mock_result.returncode = 2
    mock_result.stderr = "TASK [fail] FAILED"
    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Pre-hardening playbook failed"):
            builder_mod._run_prehard_ansible(playbook, "10.0.0.1")
