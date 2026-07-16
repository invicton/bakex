# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Edge-case and negative-path tests not covered by the primary API test files.

Covers:
  EC-01  Blueprint listing degrades gracefully when a file is unreadable/corrupt
  EC-02  Blueprint listing degrades gracefully when a file has schema errors
  EC-03  Blueprint validate with empty body → {valid: false}
  EC-04  Blueprint upload with valid YAML but missing required fields → 422
  EC-05  Blueprint upload with empty file → 422
  EC-06  Webhook fire exception is swallowed (never propagates to caller)
  EC-07  Webhook fire to URL that raises ConnectError completes without raising
  EC-08  Pipeline scan missing required field (image_id) → 422
  EC-09  Auditor scan-image with unknown profile → 404
  EC-10  API key secret not re-exposed on GET /api/api-keys
  EC-11  Blueprint listing returns no error objects when all files are valid
  EC-12  Builder OS catalog always returns non-empty list
  EC-13  Builder instance-types returns list for known OS/provider
  EC-14  Pipeline build with blueprint_yaml that has null controls → 200 (not 500)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import yaml

import bakex.core.notifications as notif_mod

# ---------------------------------------------------------------------------
# Shared YAML fixtures
# ---------------------------------------------------------------------------

_VALID_BLUEPRINT_YAML = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: ec-valid-profile
  version: "1.0.0"
  description: Edge case test profile
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""

_MISSING_COMPLIANCE_YAML = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: ec-missing-compliance
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
"""

_CONTROLS_NULL_YAML = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: ec-null-controls
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
controls:
"""


# ---------------------------------------------------------------------------
# EC-01: Listing with an unreadable/corrupt YAML file in profiles dir
# ---------------------------------------------------------------------------


def test_blueprint_listing_survives_corrupt_file(client, tmp_path, monkeypatch):
    """A corrupt YAML in the profiles dir must produce an error object in the
    list, but must not cause a 500 — the remaining valid profiles still appear.
    """
    from bakex.config import settings

    # Write one valid + one corrupt profile file into a fresh tmp dir
    valid_data = yaml.dump(
        {
            "bakex_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "ec-good-profile", "version": "1.0.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
        }
    )
    (tmp_path / "good.yaml").write_text(valid_data)
    (tmp_path / "corrupt.yaml").write_text("key: [\nnot valid yaml{{{")

    monkeypatch.setattr(settings, "profiles_dir", tmp_path)

    resp = client.get("/api/blueprints/")
    assert resp.status_code == 200
    items = resp.json()

    names = [item.get("name") for item in items if "name" in item]
    errors = [item for item in items if "error" in item]

    assert "ec-good-profile" in names, "Valid profile must appear in listing"
    assert len(errors) >= 1, "Corrupt file must produce an error object, not crash"


# ---------------------------------------------------------------------------
# EC-02: Listing with a schema-invalid YAML file (missing required fields)
# ---------------------------------------------------------------------------


def test_blueprint_listing_survives_schema_invalid_file(client, tmp_path, monkeypatch):
    """A YAML file that parses but fails Pydantic validation must return an
    error object for that file, not propagate a 500.
    """
    from bakex.config import settings

    valid_data = yaml.dump(
        {
            "bakex_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "ec-good-2", "version": "1.0.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
        }
    )
    (tmp_path / "good2.yaml").write_text(valid_data)
    # Valid YAML but missing 'compliance' → Pydantic ValidationError
    (tmp_path / "bad_schema.yaml").write_text(
        "bakex_version: '0.1.0'\nkind: ComplianceProfile\nmetadata:\n  name: bad\n  version: '1.0.0'\n"
        "target:\n  os: ubuntu22.04\n  provider: aws\n  base_image: ami-00\n"
    )

    monkeypatch.setattr(settings, "profiles_dir", tmp_path)

    resp = client.get("/api/blueprints/")
    assert resp.status_code == 200
    items = resp.json()

    names = [item.get("name") for item in items if "name" in item]
    errors = [item for item in items if "error" in item]

    assert "ec-good-2" in names
    assert len(errors) >= 1


# ---------------------------------------------------------------------------
# EC-03: Blueprint validate with empty body
# ---------------------------------------------------------------------------


def test_validate_blueprint_empty_body_returns_invalid(client):
    resp = client.post(
        "/api/blueprints/validate",
        content=b"",
        headers={"Content-Type": "application/yaml"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False


# ---------------------------------------------------------------------------
# EC-04: Blueprint upload with valid YAML but missing 'compliance' section
# ---------------------------------------------------------------------------


def test_upload_blueprint_missing_compliance_returns_422(client, user_profiles_tmp):
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("missing-compliance.yaml", _MISSING_COMPLIANCE_YAML, "application/yaml")},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# EC-05: Blueprint upload with zero-byte file
# ---------------------------------------------------------------------------


def test_upload_blueprint_empty_file_returns_422(client, user_profiles_tmp):
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("empty.yaml", b"", "application/yaml")},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# EC-06: fire_webhook swallows all exceptions — never raises to caller
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_never_raises_on_exception():
    """fire_webhook is documented as 'best-effort, never raises'. Verify that
    even if httpx raises ConnectError, the coroutine completes cleanly.
    """
    import httpx

    notif_mod._webhooks.clear()
    notif_mod.register_webhook("https://unreachable.example.invalid/hook", ["scan.complete"])

    # Patch httpx.AsyncClient to raise ConnectError on post
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    with patch("bakex.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        mock_httpx.ConnectError = httpx.ConnectError
        # Must complete without raising
        await notif_mod.fire_webhook("scan.complete", {"job_id": "ec-06"})

    notif_mod._webhooks.clear()


# ---------------------------------------------------------------------------
# EC-07: fire_webhook with timeout exception — still no raise
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fire_webhook_never_raises_on_timeout():
    import httpx

    notif_mod._webhooks.clear()
    notif_mod.register_webhook("https://slow.example.invalid/hook", ["build.complete"])

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

    with patch("bakex.core.notifications.httpx") as mock_httpx:
        mock_httpx.AsyncClient.return_value = mock_client
        mock_httpx.TimeoutException = httpx.TimeoutException
        await notif_mod.fire_webhook("build.complete", {"job_id": "ec-07"})

    notif_mod._webhooks.clear()


# ---------------------------------------------------------------------------
# EC-08: Pipeline scan missing required field (image_id) → 422
# ---------------------------------------------------------------------------


def test_pipeline_scan_missing_image_id_returns_422(client, api_key):
    resp = client.post(
        "/api/pipeline/scan",
        json={
            "provider": "aws",
            "region": "us-east-1",
            "compliance_profile": "test-ubuntu22-cis",
        },
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# EC-09: Auditor scan-image with unknown profile → 404
# ---------------------------------------------------------------------------


def test_auditor_scan_image_unknown_profile_returns_404(client):
    resp = client.post(
        "/api/auditor/scan-image",
        json={
            "image_id": "ami-test-001",
            "provider": "aws",
            "region": "us-east-1",
            "os": "ubuntu22.04",
            "compliance_profile": "no-such-profile-xyz",
            "instance_type": "t3.medium",
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# EC-10: API key secret not exposed on GET /api/api-keys
# ---------------------------------------------------------------------------


def test_api_key_secret_not_in_list(client):
    """Token/secret must only be returned on creation — never re-exposed in list."""
    client.post("/api/api-keys", json={"label": "test-expose"})
    resp = client.get("/api/api-keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) >= 1
    for key in keys:
        assert "token" not in key, "Raw token must not appear in list response"
        assert "secret" not in key, "Secret must not appear in list response"


# ---------------------------------------------------------------------------
# EC-11: Blueprint listing has no error objects when all profiles are valid
# ---------------------------------------------------------------------------


def test_blueprint_listing_no_errors_when_all_valid(client):
    """With the standard test profile, no error objects should appear in the list."""
    resp = client.get("/api/blueprints/")
    assert resp.status_code == 200
    items = resp.json()
    errors = [item for item in items if "error" in item and "name" not in item]
    assert len(errors) == 0, f"Unexpected error objects in listing: {errors}"


# ---------------------------------------------------------------------------
# EC-12: Builder OS catalog returns non-empty list
# ---------------------------------------------------------------------------


def test_builder_os_catalog_non_empty(client):
    resp = client.get("/api/builder/os-catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data.get("os_list"), list)
    assert len(data["os_list"]) > 0


# ---------------------------------------------------------------------------
# EC-13: Builder instance-types returns list for known OS/provider
# ---------------------------------------------------------------------------


def test_builder_instance_types_for_ubuntu_aws(client):
    resp = client.get("/api/builder/instance-types?os=ubuntu22.04&provider=aws")
    assert resp.status_code == 200
    data = resp.json()
    # Response is {"types": [...]} with label/value pairs
    types = data.get("types", data) if isinstance(data, dict) else data
    assert isinstance(types, list)
    assert len(types) > 0


# ---------------------------------------------------------------------------
# EC-14: Pipeline build with blueprint_yaml where controls is null → 422
# (controls: null fails Pydantic validation — schema must reject it)
# ---------------------------------------------------------------------------


def test_pipeline_build_null_controls_blueprint_returns_422(client, api_key):
    resp = client.post(
        "/api/pipeline/build",
        json={"blueprint_yaml": _CONTROLS_NULL_YAML, "wait": False},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 422
