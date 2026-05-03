# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""UI route tests — verify all page routes return 200 with HTML content."""

from __future__ import annotations

import stratum.core.auditor as audit_mod
import stratum.core.builder as builder_mod
from stratum.core.auditor import AuditJob, AuditStatus
from stratum.core.builder import BuildJob

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Integrations pages
# ---------------------------------------------------------------------------


def test_integrations_page_renders(client):
    resp = client.get("/integrations")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_integrations_provider_form_aws(client):
    resp = client.get("/integrations/aws/form")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_integrations_provider_form_generic_provider(client):
    resp = client.get("/integrations/nonexistent_provider/form")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Blueprints pages
# ---------------------------------------------------------------------------


def test_blueprints_page_renders(client, profiles_tmp, monkeypatch):
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    resp = client.get("/blueprints")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_blueprint_studio_page_renders(client, profiles_tmp, monkeypatch):
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    resp = client.get("/blueprints/studio/test-ubuntu22-cis")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_blueprint_studio_not_found(client, profiles_tmp, monkeypatch):
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    resp = client.get("/blueprints/studio/nonexistent-profile-xyz")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Builder pages
# ---------------------------------------------------------------------------


def test_builder_page_renders(client):
    resp = client.get("/builder")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_wizard_step1_renders(client):
    resp = client.get("/builder/wizard/step1")
    assert resp.status_code == 200


def test_wizard_step2_renders(client):
    resp = client.get("/builder/wizard/step2?os=ubuntu22.04&provider=aws&min_root_gb=20")
    assert resp.status_code == 200


def test_wizard_step2_unknown_os(client):
    resp = client.get("/builder/wizard/step2?os=unknown&provider=gcp")
    assert resp.status_code == 200


def test_wizard_step3_renders(client):
    resp = client.get("/builder/wizard/step3")
    assert resp.status_code == 200


def test_wizard_step4_renders(client):
    resp = client.get("/builder/wizard/step4?os=ubuntu22.04&supported_tiers=cis-l1,cis-l2")
    assert resp.status_code == 200


def test_wizard_step5_renders(client):
    resp = client.get("/builder/wizard/step5")
    assert resp.status_code == 200


def test_builder_run_page_no_job(client):
    resp = client.get("/builder/run/no-such-job-id")
    assert resp.status_code == 200


def test_builder_run_page_with_job(client):
    job = BuildJob(profile_name="test", provider_name="aws")
    builder_mod._jobs[job.id] = job
    resp = client.get(f"/builder/run/{job.id}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auditor pages
# ---------------------------------------------------------------------------


def test_auditor_page_renders(client, profiles_tmp, monkeypatch):
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    resp = client.get("/auditor")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_auditor_results_page_no_job(client):
    resp = client.get("/auditor/results/no-such-job")
    assert resp.status_code == 200


def test_auditor_results_page_with_job(client):
    job = AuditJob(target_host="10.0.0.1", profile_name="test-profile")
    audit_mod._audit_jobs[job.id] = job
    resp = client.get(f"/auditor/results/{job.id}")
    assert resp.status_code == 200


def test_scan_image_page_renders(client, profiles_tmp, monkeypatch):
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    resp = client.get("/auditor/scan-image")
    assert resp.status_code == 200


def test_scan_image_results_not_found(client):
    resp = client.get("/auditor/scan-image/no-such-job")
    assert resp.status_code == 404


def test_scan_image_results_with_job(client):
    job = AuditJob(image_id="ami-test", provider="aws", profile_name="test")
    job.status = AuditStatus.COMPLETE
    audit_mod._audit_jobs[job.id] = job
    resp = client.get(f"/auditor/scan-image/{job.id}")
    assert resp.status_code == 200


def test_auditor_history_page_renders(client):
    resp = client.get("/auditor/history")
    assert resp.status_code == 200


def test_auditor_compare_page_renders(client):
    j1 = AuditJob(target_host="h1", profile_name="p")
    j2 = AuditJob(target_host="h2", profile_name="p")
    audit_mod._audit_jobs[j1.id] = j1
    audit_mod._audit_jobs[j2.id] = j2
    resp = client.get(f"/auditor/compare/{j1.id}/{j2.id}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Scanner wizard pages
# ---------------------------------------------------------------------------


def test_scanner_wizard_renders(client):
    resp = client.get("/auditor/scanner")
    assert resp.status_code == 200


def test_scanner_step1_renders(client):
    resp = client.get("/auditor/scanner/step1")
    assert resp.status_code == 200


def test_scanner_step2_renders(client, profiles_tmp, monkeypatch):
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    resp = client.get("/auditor/scanner/step2?os=ubuntu22.04&provider=aws")
    assert resp.status_code == 200


def test_scanner_step3_renders(client):
    resp = client.get("/auditor/scanner/step3")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Settings pages
# ---------------------------------------------------------------------------


def test_api_keys_settings_page_renders(client):
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_webhooks_settings_page_renders(client):
    resp = client.get("/settings/webhooks")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Agent page
# ---------------------------------------------------------------------------


def test_agent_page_renders(client, profiles_tmp, monkeypatch):
    from stratum.config import settings

    monkeypatch.setattr(settings, "profiles_dir", profiles_tmp)
    resp = client.get("/agent")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
