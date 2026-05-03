# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API integration tests for /api/registry endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from stratum.core.blueprint import ComplianceProfile

# ---------------------------------------------------------------------------
# Helpers — build a minimal ComplianceProfile for mock returns
# ---------------------------------------------------------------------------


def _make_profile(name: str = "test-profile") -> ComplianceProfile:
    return ComplianceProfile.model_validate(
        {
            "stratum_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": name, "version": "1.0.0"},
            "target": {
                "os": "ubuntu22.04",
                "provider": "aws",
                "base_image": "ami-00000000",
            },
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
        }
    )


# ---------------------------------------------------------------------------
# GET /api/registry/ — list profiles
# ---------------------------------------------------------------------------


def test_list_registry_profiles_returns_200(client):
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    with patch("stratum.api.registry.get_registry", return_value=mock_registry):
        resp = client.get("/api/registry/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_registry_profiles_returns_profile_fields(client):
    profile = _make_profile("ubuntu22-cis-l1-aws")
    mock_registry = MagicMock()
    mock_registry.list.return_value = [profile]
    with patch("stratum.api.registry.get_registry", return_value=mock_registry):
        resp = client.get("/api/registry/")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["name"] == "ubuntu22-cis-l1-aws"
    assert item["os"] == "ubuntu22.04"
    assert item["provider"] == "aws"
    assert "benchmark" in item
    assert "version" in item


def test_list_registry_profiles_multiple(client):
    profiles = [_make_profile(f"profile-{i}") for i in range(3)]
    mock_registry = MagicMock()
    mock_registry.list.return_value = profiles
    with patch("stratum.api.registry.get_registry", return_value=mock_registry):
        resp = client.get("/api/registry/")
    assert len(resp.json()) == 3


# ---------------------------------------------------------------------------
# POST /api/registry/sync — triggers sync, returns HTML
# ---------------------------------------------------------------------------


def test_sync_registry_returns_html(client):
    mock_registry = MagicMock()
    mock_registry.sync = AsyncMock(return_value=["ubuntu22-cis-l1"])
    with patch("stratum.api.registry.get_registry", return_value=mock_registry):
        resp = client.post("/api/registry/sync")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_sync_registry_reports_synced_count(client):
    mock_registry = MagicMock()
    mock_registry.sync = AsyncMock(return_value=["p1", "p2", "p3"])
    with patch("stratum.api.registry.get_registry", return_value=mock_registry):
        resp = client.post("/api/registry/sync")
    assert "3" in resp.text


def test_sync_registry_empty_result_warns(client):
    mock_registry = MagicMock()
    mock_registry.sync = AsyncMock(return_value=[])
    with patch("stratum.api.registry.get_registry", return_value=mock_registry):
        resp = client.post("/api/registry/sync")
    assert resp.status_code == 200
    assert "No profiles synced" in resp.text or "0" in resp.text or "unavailable" in resp.text.lower()


def test_sync_registry_single_profile_no_plural_s(client):
    mock_registry = MagicMock()
    mock_registry.sync = AsyncMock(return_value=["only-one"])
    with patch("stratum.api.registry.get_registry", return_value=mock_registry):
        resp = client.post("/api/registry/sync")
    # "1 profile" — no trailing 's'
    assert "profiles" not in resp.text, f"Expected singular 'profile', got: {resp.text}"
    assert "profile" in resp.text
