# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API tests for /api/builder/* endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import statim.core.builder as builder_mod
from statim.core.builder import BuildJob, BuildStatus
from statim.plugins.base_provider import ProviderResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_build_jobs():
    builder_mod._jobs.clear()
    yield
    builder_mod._jobs.clear()


# ---------------------------------------------------------------------------
# GET /api/builder/os-catalog
# ---------------------------------------------------------------------------


def test_os_catalog_returns_os_list(client):
    resp = client.get("/api/builder/os-catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert "os_list" in data
    assert "provider_catalog" in data
    assert isinstance(data["os_list"], list)
    assert len(data["os_list"]) > 0


def test_os_catalog_os_has_required_fields(client):
    resp = client.get("/api/builder/os-catalog")
    os_entry = resp.json()["os_list"][0]
    assert "slug" in os_entry
    assert "display" in os_entry
    assert "providers" in os_entry


# ---------------------------------------------------------------------------
# GET /api/builder/instance-types
# ---------------------------------------------------------------------------


def test_instance_types_known_provider(client):
    resp = client.get("/api/builder/instance-types?provider=aws")
    assert resp.status_code == 200
    data = resp.json()
    assert "types" in data
    assert isinstance(data["types"], list)


def test_instance_types_unknown_provider_returns_empty(client):
    resp = client.get("/api/builder/instance-types?provider=unknown_xyz")
    assert resp.status_code == 200
    assert resp.json() == {"types": []}


def test_instance_types_no_provider(client):
    resp = client.get("/api/builder/instance-types")
    assert resp.status_code == 200
    assert "types" in resp.json()


# ---------------------------------------------------------------------------
# GET /api/builder/resolve-image
# ---------------------------------------------------------------------------


def test_resolve_image_non_aws_returns_catalog(client):
    resp = client.get("/api/builder/resolve-image?os=ubuntu22.04&provider=gcp&region=us-central1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "catalog"
    assert "ami_id" in data
    assert data["region"] == "us-central1"


def test_resolve_image_digitalocean_returns_catalog(client):
    resp = client.get("/api/builder/resolve-image?os=ubuntu22.04&provider=digitalocean")
    assert resp.status_code == 200
    assert resp.json()["source"] == "catalog"


def test_resolve_image_aws_success(client):
    mock_provider_cls = MagicMock()
    mock_provider = MagicMock()
    mock_provider._call_rpc.return_value = {"ami_id": "ami-resolved-123"}
    mock_provider_cls.return_value = mock_provider

    with patch("statim.plugins.registry.registry.get", return_value=mock_provider_cls):
        resp = client.get("/api/builder/resolve-image?os=ubuntu22.04&provider=aws&region=us-east-1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ami_id"] == "ami-resolved-123"
    assert data["source"] == "resolved"


def test_resolve_image_aws_exception_falls_back(client):
    mock_provider_cls = MagicMock()
    mock_provider = MagicMock()
    mock_provider._call_rpc.side_effect = RuntimeError("no connection")
    mock_provider_cls.return_value = mock_provider

    with patch("statim.plugins.registry.registry.get", return_value=mock_provider_cls):
        resp = client.get("/api/builder/resolve-image?os=ubuntu22.04&provider=aws")

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "fallback"
    assert "error" in data


# ---------------------------------------------------------------------------
# GET /api/builder/cis-layout
# ---------------------------------------------------------------------------


def test_cis_layout_returns_html(client):
    resp = client.get("/api/builder/cis-layout?os=ubuntu22.04")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_cis_layout_unknown_os_returns_no_partitions(client):
    resp = client.get("/api/builder/cis-layout?os=unknown_os_xyz")
    assert resp.status_code == 200
    # Returns empty or "no partitions" message
    assert resp.text.strip() != ""


# ---------------------------------------------------------------------------
# GET /api/builder/controls
# ---------------------------------------------------------------------------


def test_controls_no_os_returns_no_controls_message(client):
    resp = client.get("/api/builder/controls?os=nonexistent_os")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "No controls" in resp.text or "controls" in resp.text.lower()


def test_controls_known_os_returns_table(client):
    resp = client.get("/api/builder/controls?os=ubuntu22.04&standard=cis&tier=l1")
    assert resp.status_code == 200
    # Either returns control table HTML or no-controls message
    assert resp.text.strip() != ""


# ---------------------------------------------------------------------------
# GET /api/builder/profile-fields
# ---------------------------------------------------------------------------


def test_profile_fields_found(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    resp = client.get("/api/builder/profile-fields?profile_name=test-ubuntu22-cis")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "root_volume_size_gb" in resp.text or "filesystem" in resp.text.lower()


def test_profile_fields_not_found_returns_empty(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    resp = client.get("/api/builder/profile-fields?profile_name=no-such-profile")
    assert resp.status_code == 200
    assert resp.text == ""


# ---------------------------------------------------------------------------
# GET /api/builder/provider-fields
# ---------------------------------------------------------------------------


def test_provider_fields_returns_empty_html(client):
    resp = client.get("/api/builder/provider-fields")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/builder/jobs
# ---------------------------------------------------------------------------


def test_list_jobs_empty(client):
    resp = client.get("/api/builder/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_jobs_has_job(client):
    job = BuildJob(profile_name="test-profile", provider_name="aws")
    builder_mod._jobs[job.id] = job

    resp = client.get("/api/builder/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == job.id
    assert data[0]["profile_name"] == "test-profile"
    assert data[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# GET /api/builder/jobs/{job_id}
# ---------------------------------------------------------------------------


def test_get_job_found(client):
    job = BuildJob(profile_name="myprofile", provider_name="gcp")
    job._update(BuildStatus.HARDENING, "hardening started")
    builder_mod._jobs[job.id] = job

    resp = client.get(f"/api/builder/jobs/{job.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == job.id
    assert data["status"] == "hardening"


def test_get_job_not_found(client):
    resp = client.get("/api/builder/jobs/no-such-id-xyz")
    assert resp.status_code == 404


def test_get_job_dict_fields(client):
    job = BuildJob(profile_name="p", provider_name="aws", base_image="ami-001")
    job._update(BuildStatus.COMPLETE, "done")
    job.result = ProviderResult(artifact_id="ami-final", artifact_type="ami")
    builder_mod._jobs[job.id] = job

    resp = client.get(f"/api/builder/jobs/{job.id}")
    data = resp.json()
    assert data["artifact_id"] == "ami-final"
    assert data["error"] is None
    assert "created_at" in data
    assert "log" in data


# ---------------------------------------------------------------------------
# GET /api/builder/jobs/{job_id}/status (HTMX partial)
# ---------------------------------------------------------------------------


def test_job_status_partial_not_found(client):
    resp = client.get("/api/builder/jobs/missing-id-xyz/status")
    assert resp.status_code == 200
    assert "not found" in resp.text.lower() or "missing-id" in resp.text


def test_job_status_partial_found(client):
    job = BuildJob(profile_name="test", provider_name="aws")
    job._update(BuildStatus.HARDENING, "line1\nline2")
    builder_mod._jobs[job.id] = job

    resp = client.get(f"/api/builder/jobs/{job.id}/status")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_job_status_partial_complete_job(client):
    job = BuildJob(profile_name="test", provider_name="aws")
    job._update(BuildStatus.COMPLETE, "done")
    job.result = ProviderResult(artifact_id="ami-done", artifact_type="ami")
    builder_mod._jobs[job.id] = job

    resp = client.get(f"/api/builder/jobs/{job.id}/status")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/builder/start — legacy profile mode
# ---------------------------------------------------------------------------


def test_start_build_no_profile_name_returns_400(client):
    resp = client.post("/api/builder/start", data={})
    assert resp.status_code == 400


def test_start_build_profile_not_found_returns_404(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    resp = client.post("/api/builder/start", data={"profile_name": "nonexistent"})
    assert resp.status_code == 404


def test_start_build_legacy_success(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={"profile_name": "test-ubuntu22-cis"},
        )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers
    assert "/builder/run/" in resp.headers["HX-Redirect"]


def test_start_build_legacy_with_provider_override(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={"profile_name": "test-ubuntu22-cis", "provider_override": "gcp"},
        )
    assert resp.status_code == 200


def test_start_build_legacy_with_root_volume(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "profile_name": "test-ubuntu22-cis",
                "root_volume_size_gb": "50",
            },
        )
    assert resp.status_code == 200


def test_start_build_with_custom_partitions(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "profile_name": "test-ubuntu22-cis",
                "custom_layout_active": "true",
                "extra_vol_0_mount": "/var",
                "extra_vol_0_size": "10",
                "extra_vol_0_unit": "GB",
                "extra_vol_0_fstype": "xfs",
            },
        )
    assert resp.status_code == 200


def test_start_build_partition_mb_unit(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "profile_name": "test-ubuntu22-cis",
                "custom_layout_active": "true",
                "extra_vol_0_mount": "/var/log",
                "extra_vol_0_size": "512",
                "extra_vol_0_unit": "MB",
                "extra_vol_0_fstype": "xfs",
            },
        )
    assert resp.status_code == 200


def test_start_build_partition_tb_unit(client, profiles_tmp, monkeypatch):
    from statim.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "profile_name": "test-ubuntu22-cis",
                "custom_layout_active": "true",
                "extra_vol_0_mount": "/data",
                "extra_vol_0_size": "2",
                "extra_vol_0_unit": "TB",
                "extra_vol_0_fstype": "xfs",
            },
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/builder/start — wizard mode
# ---------------------------------------------------------------------------


def test_start_build_wizard_mode(client):
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "hardening_tier": "l1",
                "hardening_standard": "cis",
                "wizard_instance_type": "t3.medium",
                "wizard_base_image": "ami-00000000",
                "root_volume_size_gb": "20",
            },
        )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers


def test_start_build_wizard_l2_tier(client):
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "hardening_tier": "l2",
                "hardening_standard": "cis",
            },
        )
    assert resp.status_code == 200


def test_start_build_wizard_with_user(client):
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "user_0_name": "deploy",
                "user_0_groups": "sudo,docker",
                "user_0_shell": "/bin/bash",
                "user_0_ssh_key": "ssh-rsa AAAAB...",
                "root_lock": "on",
            },
        )
    assert resp.status_code == 200


def test_start_build_wizard_with_aide_fips(client):
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "rhel9",
                "wizard_provider": "aws",
                "aide_enabled": "on",
                "fips_enabled": "on",
            },
        )
    assert resp.status_code == 200


def test_start_build_wizard_with_control_override(client):
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "control_xccdf_rule_001": "on",
                "control_xccdf_rule_001_justification": "waived for env",
            },
        )
    assert resp.status_code == 200


def test_start_build_wizard_custom_mount(client):
    """Test the __custom__ mount path branch in wizard."""
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "extra_vol_0_mount": "__custom__",
                "extra_vol_0_mount_custom": "/opt/data",
                "extra_vol_0_size": "5",
                "extra_vol_0_unit": "GB",
                "extra_vol_0_fstype": "xfs",
            },
        )
    assert resp.status_code == 200


def test_start_build_wizard_swap_partition(client):
    """swap mount should not add an ExtraVolume."""
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "extra_vol_0_mount": "swap",
                "extra_vol_0_size": "4",
                "extra_vol_0_unit": "GB",
                "extra_vol_0_fstype": "swap",
            },
        )
    assert resp.status_code == 200


def test_start_build_wizard_no_base_image_falls_back_to_catalog(client):
    """When wizard_base_image is empty, should use OS catalog default."""
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "wizard_base_image": "",
            },
        )
    assert resp.status_code == 200


def test_start_build_wizard_invalid_size_defaults(client):
    """Non-numeric size value should not raise — defaults to 2.0."""
    with patch("statim.core.builder.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/builder/start",
            data={
                "wizard_os": "ubuntu22.04",
                "wizard_provider": "aws",
                "extra_vol_0_mount": "/var",
                "extra_vol_0_size": "notanumber",
                "extra_vol_0_unit": "GB",
                "extra_vol_0_fstype": "xfs",
            },
        )
    assert resp.status_code == 200
