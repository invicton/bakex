# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API integration tests for /api/auditor endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from statim.core import auditor as audit_mod
from statim.core.auditor import AuditJob, AuditStatus


def _inject_complete_job(**kwargs) -> AuditJob:
    """Helper: create a complete AuditJob and register it in the in-memory store."""
    job = AuditJob(
        job_type=kwargs.get("job_type", "image_scan"),
        image_id=kwargs.get("image_id", "ami-test-001"),
        provider=kwargs.get("provider", "aws"),
        region=kwargs.get("region", "us-east-1"),
        profile_name=kwargs.get("profile_name", "test-ubuntu22-cis"),
        target_host=kwargs.get("target_host", "ami-test-001"),
        status=AuditStatus.COMPLETE,
    )
    job.grade = kwargs.get("grade", "B")
    job.score_pct = kwargs.get("score_pct", 82.5)
    job.severity_counts = kwargs.get("severity_counts", {"critical": 0, "high": 2, "medium": 5, "low": 3})
    job.results = kwargs.get(
        "results",
        {
            "findings": [
                {"rule_id": "rule_high_1", "status": "fail", "severity": "high", "title": "Rule High 1"},
            ],
            "score": 82.5,
        },
    )
    audit_mod._audit_jobs[job.id] = job
    return job


# ---------------------------------------------------------------------------
# AU-API-01: POST /api/auditor/start with valid profile → 200 + job_id
# ---------------------------------------------------------------------------


def test_start_audit_returns_job_id(client):
    with patch("statim.api.auditor.audit_service.run_audit", new=AsyncMock()):
        resp = client.post(
            "/api/auditor/start",
            json={
                "profile_name": "test-ubuntu22-cis",
                "target_host": "192.168.1.100",
                "ssh_user": "ubuntu",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert "status" in body


# ---------------------------------------------------------------------------
# AU-API-02: POST /api/auditor/start with unknown profile → 404
# ---------------------------------------------------------------------------


def test_start_audit_unknown_profile_returns_404(client):
    resp = client.post(
        "/api/auditor/start",
        json={
            "profile_name": "nonexistent-profile-xyz",
            "target_host": "192.168.1.100",
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AU-API-03: GET /api/auditor/jobs after creating two jobs → list with both
# ---------------------------------------------------------------------------


def test_list_audit_jobs_returns_all(client):
    _inject_complete_job(image_id="ami-001")
    _inject_complete_job(image_id="ami-002")

    resp = client.get("/api/auditor/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 2


# ---------------------------------------------------------------------------
# AU-API-04: GET /api/auditor/jobs/{id} valid job → 200 + correct fields
# ---------------------------------------------------------------------------


def test_get_audit_job_returns_correct_fields(client):
    job = _inject_complete_job()

    resp = client.get(f"/api/auditor/jobs/{job.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == job.id
    assert body["status"] == "complete"
    assert body["grade"] == "B"
    assert body["score_pct"] == 82.5


# ---------------------------------------------------------------------------
# AU-API-05: GET /api/auditor/jobs/{id} nonexistent → 404
# ---------------------------------------------------------------------------


def test_get_audit_job_nonexistent_returns_404(client):
    resp = client.get("/api/auditor/jobs/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AU-API-06: GET report?fmt=json → 200 + JSON report
# ---------------------------------------------------------------------------


def test_export_scan_report_json(client):
    job = _inject_complete_job()

    resp = client.get(f"/api/auditor/scan-image/{job.id}/report?fmt=json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == job.id
    assert body["grade"] == "B"


# ---------------------------------------------------------------------------
# AU-API-07: GET report?fmt=sarif → 200 + SARIF with Content-Disposition
# ---------------------------------------------------------------------------


def test_export_scan_report_sarif(client):
    job = _inject_complete_job()

    resp = client.get(f"/api/auditor/scan-image/{job.id}/report?fmt=sarif")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "2.1.0"
    assert "Content-Disposition" in resp.headers
    assert ".sarif.json" in resp.headers["Content-Disposition"]


# ---------------------------------------------------------------------------
# AU-API-08: GET report for incomplete job → 400
# ---------------------------------------------------------------------------


def test_export_report_incomplete_job_returns_400(client):
    job = AuditJob(
        job_type="image_scan",
        image_id="ami-pending",
        provider="aws",
        region="us-east-1",
        profile_name="test-ubuntu22-cis",
        target_host="ami-pending",
        status=AuditStatus.SCANNING,
    )
    audit_mod._audit_jobs[job.id] = job

    resp = client.get(f"/api/auditor/scan-image/{job.id}/report?fmt=json")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# AU-API-09: GET /jobs/{id}/compare/{baseline_id} both complete → delta
# ---------------------------------------------------------------------------


def test_compare_scans_returns_delta(client):
    baseline = _inject_complete_job(
        image_id="ami-baseline",
        results={
            "rules": [
                {"id": "rule_1", "result": "pass", "severity": "high"},
                {"id": "rule_2", "result": "pass", "severity": "medium"},
            ],
            "score": 100.0,
        },
        score_pct=100.0,
        grade="A",
    )
    current = _inject_complete_job(
        image_id="ami-current",
        results={
            "rules": [
                {"id": "rule_1", "result": "fail", "severity": "high"},
                {"id": "rule_2", "result": "pass", "severity": "medium"},
            ],
            "score": 75.0,
        },
        score_pct=75.0,
        grade="B",
    )

    resp = client.get(f"/api/auditor/jobs/{current.id}/compare/{baseline.id}")
    assert resp.status_code == 200
    delta = resp.json()
    assert "score_delta" in delta
    assert "new_failures" in delta
    assert "fixed" in delta
    assert "rule_1" in delta["new_failures"]


# ---------------------------------------------------------------------------
# AU-API-10: GET compare when one job is not complete → 400
# ---------------------------------------------------------------------------


def test_compare_scans_incomplete_job_returns_400(client):
    complete_job = _inject_complete_job()
    pending_job = AuditJob(
        job_type="image_scan",
        image_id="ami-pending",
        provider="aws",
        region="us-east-1",
        profile_name="test-ubuntu22-cis",
        target_host="ami-pending",
        status=AuditStatus.SCANNING,
    )
    audit_mod._audit_jobs[pending_job.id] = pending_job

    resp = client.get(f"/api/auditor/jobs/{complete_job.id}/compare/{pending_job.id}")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Extra: GET /api/auditor/jobs on empty store → empty list
# ---------------------------------------------------------------------------


def test_list_audit_jobs_empty_on_fresh_store(client):
    resp = client.get("/api/auditor/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# AU-BADGE-01: GET /api/auditor/scan-image/{id}/badge.svg — complete job → SVG
# ---------------------------------------------------------------------------


def test_badge_returns_svg_content_type(client):
    job = _inject_complete_job(grade="A", score_pct=94.0)
    resp = client.get(f"/api/auditor/scan-image/{job.id}/badge.svg")
    assert resp.status_code == 200
    assert "svg" in resp.headers.get("content-type", "").lower()


def test_badge_contains_grade(client):
    job = _inject_complete_job(grade="B", score_pct=82.0)
    resp = client.get(f"/api/auditor/scan-image/{job.id}/badge.svg")
    assert resp.status_code == 200
    assert "B" in resp.text


def test_badge_contains_score(client):
    job = _inject_complete_job(grade="A", score_pct=94.0)
    resp = client.get(f"/api/auditor/scan-image/{job.id}/badge.svg")
    assert resp.status_code == 200
    assert "94" in resp.text


def test_badge_not_found_returns_404(client):
    resp = client.get("/api/auditor/scan-image/nonexistent-job-id/badge.svg")
    assert resp.status_code == 404


def test_badge_incomplete_job_returns_202(client):
    job = AuditJob(
        job_type="image_scan",
        image_id="ami-scanning",
        provider="aws",
        region="us-east-1",
        profile_name="test-ubuntu22-cis",
        target_host="ami-scanning",
        status=AuditStatus.SCANNING,
    )
    audit_mod._audit_jobs[job.id] = job
    resp = client.get(f"/api/auditor/scan-image/{job.id}/badge.svg")
    assert resp.status_code == 202


def test_badge_grade_a_has_green_color(client):
    job = _inject_complete_job(grade="A", score_pct=95.0)
    resp = client.get(f"/api/auditor/scan-image/{job.id}/badge.svg")
    # A-grade badge uses green fill
    assert "#" in resp.text  # some hex color present in the SVG


def test_badge_grade_f_has_red_color(client):
    job = _inject_complete_job(grade="F", score_pct=22.0)
    resp = client.get(f"/api/auditor/scan-image/{job.id}/badge.svg")
    assert resp.status_code == 200
    assert "F" in resp.text
