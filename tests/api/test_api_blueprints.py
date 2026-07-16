# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Blueprint CRUD API endpoint tests."""

from __future__ import annotations

from pathlib import Path

# All fixtures (client, api_key, profiles_tmp) come from tests/api/conftest.py


# ---------------------------------------------------------------------------
# GET /api/blueprints/ — list
# ---------------------------------------------------------------------------


def test_list_blueprints_returns_list(client):
    resp = client.get("/api/blueprints/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_list_blueprints_contains_test_profile(client):
    resp = client.get("/api/blueprints/")
    assert resp.status_code == 200
    names = [p.get("name") for p in resp.json()]
    assert "test-ubuntu22-cis" in names


def test_list_blueprints_profile_has_required_fields(client):
    resp = client.get("/api/blueprints/")
    assert resp.status_code == 200
    profile = next(p for p in resp.json() if p.get("name") == "test-ubuntu22-cis")
    assert "os" in profile
    assert "provider" in profile
    assert "benchmark" in profile
    assert "path" in profile


# ---------------------------------------------------------------------------
# GET /api/blueprints/{name} — get by name
# ---------------------------------------------------------------------------


def test_get_blueprint_returns_profile(client):
    resp = client.get("/api/blueprints/test-ubuntu22-cis")
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["name"] == "test-ubuntu22-cis"


def test_get_blueprint_has_compliance_section(client):
    resp = client.get("/api/blueprints/test-ubuntu22-cis")
    assert resp.status_code == 200
    data = resp.json()
    assert "compliance" in data
    assert "benchmark" in data["compliance"]


def test_get_blueprint_not_found_returns_404(client):
    resp = client.get("/api/blueprints/no-such-profile")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/blueprints/{name}/download — download YAML
# ---------------------------------------------------------------------------


def test_download_blueprint_returns_yaml_content_type(client):
    resp = client.get("/api/blueprints/test-ubuntu22-cis/download")
    assert resp.status_code == 200
    assert "yaml" in resp.headers.get("content-type", "").lower()


def test_download_blueprint_has_attachment_header(client):
    resp = client.get("/api/blueprints/test-ubuntu22-cis/download")
    assert resp.status_code == 200
    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert "test-ubuntu22-cis" in disposition


def test_download_blueprint_not_found_returns_404(client):
    resp = client.get("/api/blueprints/no-such-profile/download")
    assert resp.status_code == 404


def test_download_blueprint_content_is_valid_yaml(client):
    import yaml

    resp = client.get("/api/blueprints/test-ubuntu22-cis/download")
    assert resp.status_code == 200
    data = yaml.safe_load(resp.content)
    assert isinstance(data, dict)
    assert data.get("metadata", {}).get("name") == "test-ubuntu22-cis"


# ---------------------------------------------------------------------------
# POST /api/blueprints/preview — HTMX Studio endpoint
# ---------------------------------------------------------------------------


def test_preview_blueprint_not_found_returns_html_error(client):
    resp = client.post(
        "/api/blueprints/preview",
        data={"profile_name": "no-such-profile"},
    )
    assert resp.status_code == 200
    assert "not found" in resp.text.lower()


def test_preview_blueprint_returns_html(client):
    resp = client.post(
        "/api/blueprints/preview",
        data={"profile_name": "test-ubuntu22-cis"},
    )
    assert resp.status_code == 200
    # Returns HTML or YAML fragment — must be non-empty
    assert len(resp.text) > 0


def test_preview_blueprint_toggle_control(client):
    # Submit controls form data for an existing profile
    resp = client.post(
        "/api/blueprints/preview",
        data={"profile_name": "test-ubuntu22-cis"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/blueprints/upload — Blueprint-as-Code upload
# ---------------------------------------------------------------------------

_UPLOAD_YAML = """\
statim_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: uploaded-test-profile
  version: "1.0.0"
  description: Uploaded via API
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""

_INVALID_KIND_YAML = """\
statim_version: "0.1.0"
kind: NotAProfile
metadata:
  name: bad-kind
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: some_benchmark
  profile: some_profile
  datastream: /some/ds.xml
"""


def test_upload_blueprint_returns_201(client, user_profiles_tmp):
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("uploaded-test-profile.yaml", _UPLOAD_YAML, "application/yaml")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "uploaded-test-profile"


def test_upload_blueprint_is_listed_after_upload(client, user_profiles_tmp):
    client.post(
        "/api/blueprints/upload",
        files={"file": ("uploaded-test-profile.yaml", _UPLOAD_YAML, "application/yaml")},
    )
    resp = client.get("/api/blueprints/")
    names = [p.get("name") for p in resp.json()]
    assert "uploaded-test-profile" in names


def test_upload_blueprint_invalid_kind_returns_422(client, user_profiles_tmp):
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("bad.yaml", _INVALID_KIND_YAML, "application/yaml")},
    )
    assert resp.status_code == 422


def test_upload_blueprint_malformed_yaml_returns_422(client, user_profiles_tmp):
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("bad.yaml", b"key: [\ninvalid yaml{{{", "application/yaml")},
    )
    assert resp.status_code == 422


def test_upload_blueprint_duplicate_name_returns_409(client, user_profiles_tmp):
    client.post(
        "/api/blueprints/upload",
        files={"file": ("uploaded-test-profile.yaml", _UPLOAD_YAML, "application/yaml")},
    )
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("uploaded-test-profile.yaml", _UPLOAD_YAML, "application/yaml")},
    )
    assert resp.status_code == 409


def test_upload_blueprint_oversized_returns_413(client, user_profiles_tmp):
    oversized = _UPLOAD_YAML + "\n# " + "x" * (512 * 1024)
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("uploaded-test-profile.yaml", oversized.encode(), "application/yaml")},
    )
    assert resp.status_code == 413


def test_upload_blueprint_path_traversal_name_rejected(client, user_profiles_tmp):
    traversal_yaml = _UPLOAD_YAML.replace("uploaded-test-profile", "../../../../tmp/evil-profile")
    resp = client.post(
        "/api/blueprints/upload",
        files={"file": ("evil.yaml", traversal_yaml.encode(), "application/yaml")},
    )
    assert resp.status_code == 422
    assert not Path("/tmp/evil-profile.yaml").exists()


# ---------------------------------------------------------------------------
# POST /api/blueprints/validate — validate without saving
# ---------------------------------------------------------------------------


def test_validate_blueprint_valid_yaml_returns_ok(client):
    resp = client.post(
        "/api/blueprints/validate",
        content=_UPLOAD_YAML,
        headers={"Content-Type": "application/yaml"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body.get("name") == "uploaded-test-profile"


def test_validate_blueprint_invalid_kind_returns_validation_error(client):
    resp = client.post(
        "/api/blueprints/validate",
        content=_INVALID_KIND_YAML,
        headers={"Content-Type": "application/yaml"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert len(body.get("errors", [])) > 0


def test_validate_blueprint_malformed_yaml_returns_validation_error(client):
    resp = client.post(
        "/api/blueprints/validate",
        content=b"key: [\ninvalid{{{",
        headers={"Content-Type": "application/yaml"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False


# ---------------------------------------------------------------------------
# DELETE /api/blueprints/{name} — remove user-uploaded blueprint
# ---------------------------------------------------------------------------


def test_delete_user_blueprint_returns_204(client, user_profiles_tmp):
    # Upload first
    client.post(
        "/api/blueprints/upload",
        files={"file": ("uploaded-test-profile.yaml", _UPLOAD_YAML, "application/yaml")},
    )
    resp = client.delete("/api/blueprints/uploaded-test-profile")
    assert resp.status_code == 204


def test_delete_user_blueprint_no_longer_listed(client, user_profiles_tmp):
    client.post(
        "/api/blueprints/upload",
        files={"file": ("uploaded-test-profile.yaml", _UPLOAD_YAML, "application/yaml")},
    )
    client.delete("/api/blueprints/uploaded-test-profile")
    resp = client.get("/api/blueprints/")
    names = [p.get("name") for p in resp.json()]
    assert "uploaded-test-profile" not in names


def test_delete_nonexistent_blueprint_returns_404(client, user_profiles_tmp):
    resp = client.delete("/api/blueprints/no-such-profile-xyz")
    assert resp.status_code == 404


def test_delete_template_blueprint_returns_403(client, user_profiles_tmp):
    # test-ubuntu22-cis is in the session profiles_tmp (not user_profiles_tmp) — cannot delete
    resp = client.delete("/api/blueprints/test-ubuntu22-cis")
    assert resp.status_code == 403
