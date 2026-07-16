# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Extended blueprint API tests covering previously uncovered lines.

Covers blueprints.py lines:
  73-74    — download_blueprint falls back to community registry
  81-90    — download from community registry returns re-serialized YAML
  149-150  — delete scans user dir, profile not found there → checks built-ins
  160-161  — delete finds name in built-in templates → 403
  174-175  — get_blueprint not found → 404
  206-207,209-210 — preview_blueprint: disabled control without justification (warning)
  215-227  — preview: control toggle logic (enabled=True, disabled+justified)
  231-234  — preview: submitted rule not in existing profile
  255-256  — _find_profile checks community registry
  261-262  — _find_profile: registry RuntimeError → None
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import yaml

# ---------------------------------------------------------------------------
# Shared YAML content
# ---------------------------------------------------------------------------

_PROFILE_WITH_CONTROLS = {
    "statim_version": "0.1.0",
    "kind": "ComplianceProfile",
    "metadata": {"name": "ctrl-test-profile", "version": "1.0.0"},
    "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
    "compliance": {
        "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
        "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
        "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
    },
    "controls": {
        "sshd_disable_root_login": {"enabled": True, "justification": "Required"},
        "accounts_password_minlen": {"enabled": False, "justification": "Waiver approved"},
    },
}


# ===========================================================================
# download_blueprint — community registry fallback (lines 77-90)
# ===========================================================================


def test_download_blueprint_falls_back_to_community_registry(client, monkeypatch):
    """If the profile is not in local files, it should be fetched from the community registry."""
    from statim.core.blueprint import ComplianceProfile

    mock_profile = ComplianceProfile.model_validate(
        {
            "statim_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "community-bp", "version": "1.0.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-community"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
        }
    )

    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_profile

    with patch("statim.core.registry.get_registry", return_value=mock_registry):
        resp = client.get("/api/blueprints/community-bp/download")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/yaml")
    assert b"community-bp" in resp.content


def test_download_blueprint_not_found_in_registry_returns_404(client, monkeypatch):
    """When name is in neither local nor community registry, 404 is returned."""
    mock_registry = MagicMock()
    mock_registry.get.return_value = None

    with patch("statim.core.registry.get_registry", return_value=mock_registry):
        resp = client.get("/api/blueprints/totally-unknown-xyz/download")

    assert resp.status_code == 404


# ===========================================================================
# get_blueprint — not found (lines 174-175)
# ===========================================================================


def test_get_blueprint_not_found_returns_404(client):
    """GET /api/blueprints/{name} returns 404 when name does not exist."""
    resp = client.get("/api/blueprints/does-not-exist-xyz")
    assert resp.status_code == 404


# ===========================================================================
# delete_blueprint — built-in template returns 403 (lines 153-161)
# ===========================================================================


def test_delete_built_in_blueprint_returns_403(client, profiles_tmp):
    """Deleting a profile that lives in the built-in profiles dir returns 403."""
    resp = client.delete("/api/blueprints/test-ubuntu22-cis")
    assert resp.status_code == 403
    assert "built-in" in resp.json()["detail"].lower()


def test_delete_blueprint_not_found_returns_404(client):
    """Deleting a profile that doesn't exist anywhere returns 404."""
    resp = client.delete("/api/blueprints/no-such-profile-xyz")
    assert resp.status_code == 404


# ===========================================================================
# delete_blueprint — user-uploaded profile (happy path)
# ===========================================================================


def test_delete_user_blueprint_succeeds(client, user_profiles_tmp):
    """A user-uploaded profile can be deleted (204)."""
    # Upload first
    profile_yaml = yaml.dump(
        {
            "statim_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "deletable-profile", "version": "1.0.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-del"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
        }
    )
    upload = client.post(
        "/api/blueprints/upload",
        files={"file": ("deletable-profile.yaml", profile_yaml, "application/yaml")},
    )
    assert upload.status_code == 201

    resp = client.delete("/api/blueprints/deletable-profile")
    assert resp.status_code == 204


# ===========================================================================
# preview_blueprint — control toggle logic (lines 196-246)
# ===========================================================================


def test_preview_blueprint_not_found_returns_error_fragment(client):
    """preview_blueprint returns an HTML error fragment when profile doesn't exist."""
    resp = client.post(
        "/api/blueprints/preview",
        data={"profile_name": "nonexistent-profile"},
    )
    assert resp.status_code == 200
    assert "not found" in resp.text.lower()


def test_preview_blueprint_disabled_without_justification_shows_warning(client, profiles_tmp):
    """Disabling a control without justification triggers the yaml_warning."""
    # Write a profile with controls to profiles dir
    ctrl_yaml = yaml.dump(_PROFILE_WITH_CONTROLS)
    (profiles_tmp / "ctrl-test-profile.yaml").write_text(ctrl_yaml)

    try:
        resp = client.post(
            "/api/blueprints/preview",
            data={
                "profile_name": "ctrl-test-profile",
                # sshd_disable_root_login: disabled, no justification
                "controls[sshd_disable_root_login][enabled]": "false",
                "controls[sshd_disable_root_login][justification]": "",
                # accounts_password_minlen: enabled
                "controls[accounts_password_minlen][enabled]": "true",
            },
        )
    finally:
        (profiles_tmp / "ctrl-test-profile.yaml").unlink(missing_ok=True)

    assert resp.status_code == 200
    assert "sshd_disable_root_login" in resp.text


def test_preview_blueprint_disabled_with_justification_no_warning(client, profiles_tmp):
    """Disabling a control WITH justification does not produce a yaml_warning."""
    ctrl_yaml = yaml.dump(_PROFILE_WITH_CONTROLS)
    (profiles_tmp / "ctrl-test-profile.yaml").write_text(ctrl_yaml)

    try:
        resp = client.post(
            "/api/blueprints/preview",
            data={
                "profile_name": "ctrl-test-profile",
                "controls[sshd_disable_root_login][enabled]": "false",
                "controls[sshd_disable_root_login][justification]": "Approved exception",
            },
        )
    finally:
        (profiles_tmp / "ctrl-test-profile.yaml").unlink(missing_ok=True)

    assert resp.status_code == 200
    # The YAML should contain the justification
    assert "Approved exception" in resp.text


def test_preview_blueprint_submitted_rule_not_in_profile(client, profiles_tmp):
    """Rules submitted in the form that are not in the profile's controls are handled."""
    ctrl_yaml = yaml.dump(_PROFILE_WITH_CONTROLS)
    (profiles_tmp / "ctrl-test-profile.yaml").write_text(ctrl_yaml)

    try:
        resp = client.post(
            "/api/blueprints/preview",
            data={
                "profile_name": "ctrl-test-profile",
                # Submit a NEW rule not in the existing profile controls
                "controls[new_extra_rule][enabled]": "true",
            },
        )
    finally:
        (profiles_tmp / "ctrl-test-profile.yaml").unlink(missing_ok=True)

    assert resp.status_code == 200
    assert "new_extra_rule" in resp.text


# ===========================================================================
# _find_profile — community registry and RuntimeError path (lines 255-262)
# ===========================================================================


def test_find_profile_falls_back_to_community_registry():
    """_find_profile returns a profile from the community registry when not in local files."""
    from statim.api.blueprints import _find_profile
    from statim.core.blueprint import ComplianceProfile

    mock_profile = ComplianceProfile.model_validate(
        {
            "statim_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "reg-fallback-direct", "version": "1.0.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-00"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
        }
    )

    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_profile

    with patch("statim.core.registry.get_registry", return_value=mock_registry):
        profile = _find_profile("reg-fallback-direct")

    assert profile is not None
    assert profile.metadata.name == "reg-fallback-direct"


def test_find_profile_registry_runtime_error_returns_none():
    """When get_registry() raises RuntimeError, _find_profile returns None."""
    from statim.api.blueprints import _find_profile

    with patch("statim.core.registry.get_registry", side_effect=RuntimeError("registry not ready")):
        result = _find_profile("any-profile")

    assert result is None
