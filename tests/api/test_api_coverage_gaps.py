# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Coverage gap tests for api/ui.py, api/blueprints.py, and api/auditor.py.

Targets:
  api/ui.py          81-84   — integrations_provider_form: catalog file with matching provider
                   100-101   — blueprints_page: user_dir exists with extra profiles
                   106-107   — blueprints_page: load_profile raises
                   112-113   — blueprints_page: get_registry().list() raises RuntimeError
                   134-135   — blueprint_studio_page: user_dir exists
                   142-143   — blueprint_studio_page: load_profile raises
                   150-151   — blueprint_studio_page: get_registry().get() raises RuntimeError
                   250-251   — auditor_page: load_profile raises
                   280-281   — scan_image_page: load_profile raises
                   299-300   — agent_page: load_profile raises
                   341-342   — scanner_step2: load_profile raises
  api/blueprints.py   73-74  — download_blueprint: load_profile raises
                     89-90   — download_blueprint: registry.get() raises RuntimeError
                   149-150   — delete_blueprint: load_profile raises in user-dir loop
                   160-161   — delete_blueprint: load_profile raises in main profiles loop
                   174-175   — get_blueprint: load_profile raises
                   255-256   — _find_profile: load_profile raises
  api/auditor.py      188    — export_scan_report default HTML path
                      202    — compare_scans: one job not found
                      211    — compare_scans: results in findings format (no 'rules' key)
                   250-251   — _resolve_profile: load_profile raises
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import yaml

import stratum.core.auditor as audit_mod
from stratum.core.auditor import AuditJob, AuditStatus

# ---------------------------------------------------------------------------
# api/ui.py — integrations_provider_form catalog branch (lines 81-84)
# ---------------------------------------------------------------------------


def test_integrations_form_catalog_matching_provider(client, tmp_path, monkeypatch):
    """Catalog JSON with matching provider ID → plugin_meta is populated (line 81-82)."""
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    catalog = {"providers": [{"id": "aws", "name": "Amazon AWS", "version": "1.0"}]}
    (catalog_dir / "index.json").write_text(json.dumps(catalog))
    from unittest.mock import PropertyMock

    from stratum.config import Settings

    with patch.object(Settings, "catalog_dir_absolute", new_callable=PropertyMock, return_value=catalog_dir):
        resp = client.get("/integrations/aws/form")
    assert resp.status_code == 200


def test_integrations_form_catalog_bad_json(client, tmp_path, monkeypatch):
    """Corrupted catalog JSON → exception is swallowed, page still renders (lines 83-84)."""
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    (catalog_dir / "index.json").write_text("NOT JSON {{{")
    from unittest.mock import PropertyMock

    from stratum.config import Settings

    with patch.object(Settings, "catalog_dir_absolute", new_callable=PropertyMock, return_value=catalog_dir):
        resp = client.get("/integrations/aws/form")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# api/ui.py — blueprints_page branches (lines 100-101, 106-107, 112-113)
# ---------------------------------------------------------------------------


def test_blueprints_page_user_dir_has_extra_profiles(client, profiles_tmp, monkeypatch):
    """user_dir exists and differs → extra profiles appended (lines 100-101)."""
    from stratum.config import settings

    # user_dir already set by _isolate_stores fixture; add a valid profile to it
    user_dir = settings.user_profiles_dir
    extra = {
        "stratum_version": "0.1.0",
        "kind": "ComplianceProfile",
        "metadata": {"name": "user-extra-profile", "version": "1.0"},
        "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-0"},
        "compliance": {
            "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
            "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
            "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
        },
    }
    (user_dir / "extra.yaml").write_text(yaml.dump(extra))
    resp = client.get("/blueprints")
    assert resp.status_code == 200


def test_blueprints_page_load_profile_raises(client, profiles_tmp, monkeypatch):
    """load_profile raises → exception is swallowed, page still renders (lines 106-107)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("bad yaml")):
        resp = client.get("/blueprints")
    assert resp.status_code == 200


def test_blueprints_page_registry_list_raises(client, profiles_tmp, monkeypatch):
    """get_registry().list() raises RuntimeError → community_profiles = [] (lines 112-113)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    mock_reg = MagicMock()
    mock_reg.list.side_effect = RuntimeError("registry not initialised")
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("skip")):
        with patch("stratum.core.registry.get_registry", return_value=mock_reg):
            resp = client.get("/blueprints")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# api/ui.py — blueprint_studio_page branches (lines 134-135, 142-143, 150-151)
# ---------------------------------------------------------------------------


def test_blueprint_studio_user_dir_searched(client, profiles_tmp, monkeypatch):
    """user_dir exists and differs → its profiles are searched (lines 134-135)."""
    from stratum.config import settings

    user_dir = settings.user_profiles_dir
    profile_data = {
        "stratum_version": "0.1.0",
        "kind": "ComplianceProfile",
        "metadata": {"name": "user-studio-profile", "version": "1.0"},
        "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-0"},
        "compliance": {
            "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
            "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
            "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
        },
    }
    (user_dir / "user-studio-profile.yaml").write_text(yaml.dump(profile_data))
    resp = client.get("/blueprints/studio/user-studio-profile")
    assert resp.status_code == 200


def test_blueprint_studio_load_profile_raises(client, profiles_tmp, monkeypatch):
    """load_profile raises → exception swallowed, falls through to 404 (lines 142-143)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("bad")):
        with patch("stratum.core.registry.get_registry") as mock_get:
            mock_get.return_value.get.return_value = None
            resp = client.get("/blueprints/studio/nonexistent-xyz")
    assert resp.status_code == 404


def test_blueprint_studio_registry_get_raises(client, profiles_tmp, monkeypatch):
    """get_registry().get() raises RuntimeError → swallowed, 404 (lines 150-151)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    mock_reg = MagicMock()
    mock_reg.get.side_effect = RuntimeError("not ready")
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("skip")):
        with patch("stratum.core.registry.get_registry", return_value=mock_reg):
            resp = client.get("/blueprints/studio/nonexistent-xyz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# api/ui.py — auditor_page, scan_image_page, agent_page, scanner_step2
#             load_profile exception swallowed (lines 250-251, 280-281, 299-300, 341-342)
# ---------------------------------------------------------------------------


def test_auditor_page_load_profile_raises(client, profiles_tmp, monkeypatch):
    """auditor_page: load_profile raises → swallowed (lines 250-251)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("bad")):
        resp = client.get("/auditor")
    assert resp.status_code == 200


def test_scan_image_page_load_profile_raises(client, profiles_tmp, monkeypatch):
    """scan_image_page: load_profile raises → swallowed (lines 280-281)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("bad")):
        resp = client.get("/auditor/scan-image")
    assert resp.status_code == 200


def test_agent_page_load_profile_raises(client, profiles_tmp, monkeypatch):
    """agent_page: load_profile raises → swallowed (lines 299-300)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("bad")):
        resp = client.get("/agent")
    assert resp.status_code == 200


def test_scanner_step2_load_profile_raises(client, profiles_tmp, monkeypatch):
    """scanner_step2: load_profile raises → swallowed (lines 341-342)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.ui.load_profile", side_effect=ValueError("bad")):
        resp = client.get("/auditor/scanner/step2?os=ubuntu22.04&provider=aws")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# api/blueprints.py — download_blueprint exception paths (lines 73-74, 89-90)
# ---------------------------------------------------------------------------


def test_download_blueprint_load_profile_raises(client, profiles_tmp, monkeypatch):
    """download_blueprint: load_profile raises → continue (lines 73-74)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.blueprints.load_profile", side_effect=ValueError("bad")):
        with patch("stratum.core.registry.get_registry") as mock_get:
            mock_get.return_value.get.return_value = None
            resp = client.get("/api/blueprints/nonexistent-xyz/download")
    assert resp.status_code == 404


def test_download_blueprint_registry_raises(client, profiles_tmp, monkeypatch):
    """download_blueprint: get_registry().get() raises RuntimeError → pass (lines 89-90)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    mock_reg = MagicMock()
    mock_reg.get.side_effect = RuntimeError("not ready")
    with patch("stratum.api.blueprints.load_profile", side_effect=ValueError("bad")):
        with patch("stratum.core.registry.get_registry", return_value=mock_reg):
            resp = client.get("/api/blueprints/nonexistent-xyz/download")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# api/blueprints.py — delete_blueprint exception paths (lines 149-150, 160-161)
# ---------------------------------------------------------------------------


def test_delete_blueprint_user_dir_load_profile_raises(client, profiles_tmp, monkeypatch):
    """delete_blueprint: load_profile raises in user-dir loop → continue (lines 149-150)."""
    from stratum.config import settings

    user_dir = settings.user_profiles_dir
    (user_dir / "bad.yaml").write_text("NOT VALID YAML {{{{")
    resp = client.delete("/api/blueprints/bad")
    assert resp.status_code == 404


def test_delete_blueprint_main_dir_load_profile_raises(client, profiles_tmp, monkeypatch):
    """delete_blueprint: load_profile raises in main-dir loop → continue (lines 160-161)."""
    # patch load_profile to raise only for the main dir path
    with patch("stratum.api.blueprints.load_profile", side_effect=ValueError("bad")):
        resp = client.delete("/api/blueprints/nonexistent-zzz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# api/blueprints.py — get_blueprint exception path (lines 174-175)
# ---------------------------------------------------------------------------


def test_get_blueprint_load_profile_raises(client, profiles_tmp, monkeypatch):
    """get_blueprint: load_profile raises → continue, 404 (lines 174-175)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.blueprints.load_profile", side_effect=ValueError("bad")):
        resp = client.get("/api/blueprints/nonexistent-zzz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# api/blueprints.py — _find_profile exception path (lines 255-256)
# ---------------------------------------------------------------------------


def test_find_profile_load_raises_returns_none(client, profiles_tmp, monkeypatch):
    """_find_profile: load_profile raises → continue; profile not found returns HTML error (255-256)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.blueprints.load_profile", side_effect=ValueError("bad")):
        resp = client.post("/api/blueprints/preview", data={"profile_name": "nonexistent-xyz"})
    assert resp.status_code == 200
    assert "not found" in resp.text.lower() or "Profile not found" in resp.text


# ---------------------------------------------------------------------------
# api/auditor.py — export_scan_report default HTML (line 188)
# ---------------------------------------------------------------------------


def test_export_scan_report_html_default(client):
    """export_scan_report without ?fmt → returns HTML report template (line 188)."""
    job = AuditJob(image_id="ami-html-test", provider="aws", profile_name="test")
    job.status = AuditStatus.COMPLETE
    job.grade = "A"
    job.score_pct = 95.0
    job.results = {"findings": [], "score": 95.0}
    audit_mod._audit_jobs[job.id] = job
    resp = client.get(f"/api/auditor/scan-image/{job.id}/report")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# api/auditor.py — compare_scans: one job not found (line 202)
# ---------------------------------------------------------------------------


def test_compare_scans_job_not_found(client):
    """compare_scans with nonexistent job IDs → 404 (line 202)."""
    resp = client.get("/api/auditor/jobs/no-such-job/compare/also-no-such")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# api/auditor.py — compare_scans: results in findings format (lines 211-215)
# ---------------------------------------------------------------------------


def test_compare_scans_findings_format(client):
    """compare_scans with findings-format results (no 'rules' key) → _to_rules converts (line 211)."""

    current = AuditJob(image_id="ami-current", provider="aws", profile_name="test")
    current.status = AuditStatus.COMPLETE
    current.results = {
        "findings": [
            {"rule_id": "rule_1", "status": "fail", "severity": "high"},
            {"rule_id": "rule_2", "status": "pass", "severity": "low"},
        ],
        "score": 80.0,
    }

    baseline = AuditJob(image_id="ami-baseline", provider="aws", profile_name="test")
    baseline.status = AuditStatus.COMPLETE
    baseline.results = {
        "findings": [
            {"rule_id": "rule_1", "status": "pass", "severity": "high"},
        ],
        "score": 90.0,
    }

    audit_mod._audit_jobs[current.id] = current
    audit_mod._audit_jobs[baseline.id] = baseline

    with patch("stratum.openscap.parser.compute_delta", return_value={"added": [], "removed": [], "changed": []}):
        resp = client.get(f"/api/auditor/jobs/{current.id}/compare/{baseline.id}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# api/auditor.py — _resolve_profile load_profile raises (lines 250-251)
# ---------------------------------------------------------------------------


def test_audit_resolve_profile_load_raises(client, profiles_tmp, monkeypatch):
    """_resolve_profile: load_profile raises → continue, 404 (lines 250-251)."""
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    with patch("stratum.api.auditor.load_profile", side_effect=ValueError("bad")):
        resp = client.post(
            "/api/auditor/start",
            json={"target_host": "10.0.0.1", "profile_name": "nonexistent-profile"},
        )
    assert resp.status_code == 404
