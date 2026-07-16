# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API integration tests for /api/plugins endpoints — catalog, install, remove."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_catalog_id(client) -> str:
    """Return the first provider ID from the live catalog."""
    resp = client.get("/api/plugins/catalog")
    assert resp.status_code == 200
    entries = resp.json()
    assert entries, "Catalog must not be empty for plugin tests"
    return entries[0]["id"]


# ---------------------------------------------------------------------------
# GET /api/plugins/catalog
# ---------------------------------------------------------------------------


def test_get_catalog_returns_list(client):
    resp = client.get("/api/plugins/catalog")
    assert resp.status_code == 200
    catalog = resp.json()
    assert isinstance(catalog, list)
    assert len(catalog) >= 1


def test_catalog_entries_have_installed_field(client):
    resp = client.get("/api/plugins/catalog")
    for entry in resp.json():
        assert "installed" in entry, f"Entry {entry.get('id')} missing 'installed' key"
        assert isinstance(entry["installed"], bool)


def test_catalog_entries_have_id_and_name(client):
    resp = client.get("/api/plugins/catalog")
    for entry in resp.json():
        assert "id" in entry
        assert "name" in entry


# ---------------------------------------------------------------------------
# GET /api/plugins/catalog/{provider_id}/download
# ---------------------------------------------------------------------------


def test_download_catalog_script_returns_200(client):
    """digitalocean.py is in the catalog and in plugins/catalog/ — should download."""
    resp = client.get("/api/plugins/catalog/digitalocean/download")
    assert resp.status_code == 200
    assert "python" in resp.headers["content-type"]
    assert b"PROVIDER_NAME" in resp.content


def test_download_catalog_script_has_correct_disposition(client):
    resp = client.get("/api/plugins/catalog/digitalocean/download")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "digitalocean.py" in resp.headers["content-disposition"]


def test_download_nonexistent_provider_returns_404(client):
    resp = client.get("/api/plugins/catalog/does_not_exist/download")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/plugins/available — HTML partial
# ---------------------------------------------------------------------------


def test_available_plugins_returns_html(client):
    resp = client.get("/api/plugins/available")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# POST /api/plugins/install — installs into an isolated temp dir
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_plugins_dir(monkeypatch, tmp_path):
    """Redirect settings.plugins_dir to a temp dir for install/remove tests."""
    from statim.config import settings

    monkeypatch.setattr(settings, "plugins_dir", tmp_path)
    return tmp_path


def test_install_valid_provider_returns_success(client, isolated_plugins_dir):
    resp = client.post(
        "/api/plugins/install",
        data={"provider_id": "digitalocean"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "digitalocean" in resp.text.lower() or "installed" in resp.text.lower()


def test_install_copies_script_to_plugins_dir(client, isolated_plugins_dir):
    client.post("/api/plugins/install", data={"provider_id": "gcp"})
    assert (isolated_plugins_dir / "gcp.py").exists()


def test_install_unknown_provider_returns_400(client, isolated_plugins_dir):
    resp = client.post(
        "/api/plugins/install",
        data={"provider_id": "does_not_exist_xyz"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/plugins/{provider_id}/remove
# ---------------------------------------------------------------------------


def test_remove_installed_provider(client, isolated_plugins_dir):
    # Pre-create a dummy script so there is something to remove
    script = isolated_plugins_dir / "linode.py"
    script.write_bytes(b"# dummy")

    resp = client.post("/api/plugins/linode/remove")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # File should be gone
    assert not script.exists()


def test_remove_missing_provider_still_returns_200(client, isolated_plugins_dir):
    """Removing a provider whose file is already absent should not raise 500."""
    resp = client.post("/api/plugins/nonexistent_provider/remove")
    assert resp.status_code == 200
