# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Shared fixtures for API integration tests.

Strategy:
- TestClient wraps the real FastAPI app (full routing, middleware, auth)
- init_registry is patched to avoid network calls to GitHub
- audit_service.run_image_scan / run_audit are patched per-test to avoid
  cloud/Ansible execution — tests inject pre-built AuditJob state directly
- In-memory stores (api_keys, webhooks, audit_jobs) are cleared between tests
  to keep each test isolated
"""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

import bakex.core.api_keys as ak_mod
import bakex.core.notifications as notif_mod
from bakex.core import auditor as audit_mod

_TEST_ADMIN_TOKEN = "test-admin-token"

# ---------------------------------------------------------------------------
# Minimal valid profile YAML written to a temp dir for profile resolution
# ---------------------------------------------------------------------------

_PROFILE_DATA = {
    "bakex_version": "0.1.0",
    "kind": "ComplianceProfile",
    "metadata": {
        "name": "test-ubuntu22-cis",
        "version": "1.0.0",
        "description": "Test profile",
    },
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


@pytest.fixture(scope="session")
def profiles_tmp(tmp_path_factory) -> Path:
    """Create a temp profiles dir with one valid profile, used for the whole session."""
    d = tmp_path_factory.mktemp("profiles")
    (d / "test_profile.yaml").write_text(yaml.dump(_PROFILE_DATA))
    return d


@pytest.fixture
def user_profiles_tmp(tmp_path, monkeypatch):
    """Return the per-test user-profiles dir (already created by _isolate_stores)."""
    from bakex.config import settings

    return settings.user_profiles_dir


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path, monkeypatch, profiles_tmp):
    """Reset all in-memory stores and redirect file persistence before each test."""
    # Clear stores
    ak_mod._keys.clear()
    notif_mod._webhooks.clear()
    audit_mod._audit_jobs.clear()

    # Redirect file persistence to isolated temp paths
    monkeypatch.setattr(ak_mod, "_KEYS_FILE", tmp_path / "api_keys.json")
    monkeypatch.setattr(notif_mod, "_WEBHOOKS_FILE", tmp_path / "webhooks.json")
    monkeypatch.setattr(audit_mod, "_JOBS_FILE", tmp_path / "audit_jobs.json")

    # Point profile resolution to our temp profiles dir
    from bakex.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    # Isolate user profiles dir per test
    user_dir = tmp_path / "user_profiles"
    user_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "user_profiles_dir", user_dir)

    # Fixed admin token so `client` can authenticate deterministically
    monkeypatch.setattr(settings, "bakex_admin_token", _TEST_ADMIN_TOKEN)

    yield

    ak_mod._keys.clear()
    notif_mod._webhooks.clear()
    audit_mod._audit_jobs.clear()


@pytest.fixture(scope="session")
def app():
    """Return the FastAPI app with init_registry patched out (no network)."""
    from bakex.main import app as _app

    return _app


@pytest.fixture
def client(app, profiles_tmp, monkeypatch):
    """TestClient wrapping the full app. init_registry is a no-op.

    Pre-authenticated with the fixed test admin token (HTTP Basic) so existing
    tests exercising feature behaviour don't need to know about auth. Tests
    that specifically exercise the auth gate should build their own
    unauthenticated ``TestClient(app)`` instead of using this fixture.
    """
    from bakex.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)

    with patch("bakex.main.init_registry"):
        with TestClient(app, raise_server_exceptions=True) as c:
            # A default header (not `c.auth`) so tests that pass an explicit
            # Authorization header (e.g. to exercise /api/pipeline's own Bearer
            # check) override it per-request instead of an auth flow clobbering it.
            c.headers["Authorization"] = "Basic " + base64.b64encode(f"admin:{_TEST_ADMIN_TOKEN}".encode()).decode()
            yield c


@pytest.fixture
def api_key(client) -> str:
    """Create a real API key via the API and return the plaintext token."""
    resp = client.post("/api/api-keys", json={"label": "test-ci"})
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


@pytest.fixture
def mock_run_image_scan():
    """Patch run_image_scan so it injects a completed AuditJob without cloud calls."""
    from bakex.core.auditor import AuditStatus

    async def _fake_scan(image_id, provider_name, region, profile, instance_type, output_dir):
        # Find the pre-created job and mark it complete
        for job in audit_mod._audit_jobs.values():
            if job.image_id == image_id:
                job.status = AuditStatus.COMPLETE
                job.grade = "B"
                job.score_pct = 82.5
                job.severity_counts = {"critical": 0, "high": 2, "medium": 5, "low": 3}
                job.results = {
                    "findings": [
                        {"rule_id": "rule_high_1", "status": "fail", "severity": "high"},
                        {"rule_id": "rule_high_2", "status": "fail", "severity": "high"},
                    ],
                    "score": 82.5,
                }
                break

    with (
        patch("bakex.core.auditor.run_image_scan", side_effect=_fake_scan),
        patch("bakex.api.auditor.audit_service.run_image_scan", side_effect=_fake_scan),
        patch("bakex.api.pipeline.audit_service.run_image_scan", side_effect=_fake_scan),
    ):
        yield
