# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Layer 5 regression / smoke tests — REG-01 through REG-07.

Run on every CI commit against a locally starting instance (no cloud calls).
Uses FastAPI TestClient for the server-side tests so no external process is
needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import statim.core.api_keys as ak_mod
import statim.core.notifications as notif_mod
from statim.core import auditor as audit_mod

# ---------------------------------------------------------------------------
# Isolation — reset in-memory stores and redirect persistence files
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path, monkeypatch):
    ak_mod._keys.clear()
    notif_mod._webhooks.clear()
    audit_mod._audit_jobs.clear()
    monkeypatch.setattr(ak_mod, "_KEYS_FILE", tmp_path / "api_keys.json")
    monkeypatch.setattr(notif_mod, "_WEBHOOKS_FILE", tmp_path / "webhooks.json")
    monkeypatch.setattr(audit_mod, "_JOBS_FILE", tmp_path / "audit_jobs.json")
    yield
    ak_mod._keys.clear()
    notif_mod._webhooks.clear()
    audit_mod._audit_jobs.clear()


@pytest.fixture
def smoke_client(monkeypatch):
    """TestClient that patches init_registry to avoid network calls on startup."""
    from statim.config import settings
    from statim.main import app

    monkeypatch.setattr(settings, "statim_admin_token", "test-admin-token")

    with patch("statim.core.registry.init_registry"):
        with TestClient(app, raise_server_exceptions=True) as c:
            c.auth = ("admin", "test-admin-token")
            yield c


# ---------------------------------------------------------------------------
# REG-01: App starts without error
# ---------------------------------------------------------------------------


def test_app_starts_without_error(smoke_client):
    """Lifespan completes cleanly — health endpoint confirms startup is clean."""
    resp = smoke_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# REG-02: GET / returns 200 with HTML body
# ---------------------------------------------------------------------------


def test_root_returns_200_html(smoke_client):
    resp = smoke_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# REG-03: GET /api/auditor/jobs returns empty list on fresh start
# ---------------------------------------------------------------------------


def test_auditor_jobs_empty_on_fresh_start(smoke_client):
    resp = smoke_client.get("/api/auditor/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# REG-04: GET /api/api-keys returns empty list on fresh start
# ---------------------------------------------------------------------------


def test_api_keys_empty_on_fresh_start(smoke_client):
    resp = smoke_client.get("/api/api-keys")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# REG-05: Example profile loads without error
# ---------------------------------------------------------------------------


def test_example_profile_loads():
    from statim.core.blueprint import load_profile

    profile = load_profile(Path("profiles/examples/ubuntu22_cis_l1.yaml"))
    assert profile is not None
    assert profile.metadata.name != ""
    assert profile.compliance.benchmark != ""


# ---------------------------------------------------------------------------
# REG-06: local provider loads from plugins/providers
# ---------------------------------------------------------------------------


def test_local_provider_in_registry():
    from statim.plugins.loader import load_providers

    providers, _ = load_providers(Path("plugins/providers"), strict=False)
    assert "local" in providers, f"'local' not found in loaded providers: {sorted(providers)}"


# ---------------------------------------------------------------------------
# REG-07: aws and digitalocean subprocess providers load
# ---------------------------------------------------------------------------


def test_aws_and_digitalocean_providers_load():
    from statim.plugins.loader import load_providers

    providers, _ = load_providers(Path("plugins/providers"), strict=False)
    assert "aws" in providers, f"'aws' not found in loaded providers: {sorted(providers)}"
    assert "digitalocean" in providers, f"'digitalocean' not found in loaded providers: {sorted(providers)}"
