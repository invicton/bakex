# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""API integration tests for /api/pipeline endpoints — auth + scan logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from stratum.core import auditor as audit_mod
from stratum.core.auditor import AuditJob, AuditStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCAN_BODY = {
    "image_id": "ami-test-001",
    "provider": "aws",
    "region": "us-east-1",
    "compliance_profile": "test-ubuntu22-cis",
    "instance_type": "t3.medium",
    "pass_threshold": 75.0,
    "severity_threshold": "high",
    "wait": False,
}


# ---------------------------------------------------------------------------
# PL-API-01: POST /api/pipeline/scan with no API key → 401
# ---------------------------------------------------------------------------


def test_pipeline_scan_no_auth_returns_401(client):
    resp = client.post("/api/pipeline/scan", json=_SCAN_BODY)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PL-API-02: POST with invalid API key → 401
# ---------------------------------------------------------------------------


def test_pipeline_scan_invalid_key_returns_401(client):
    resp = client.post(
        "/api/pipeline/scan",
        json=_SCAN_BODY,
        headers={"X-Api-Key": "str_totally_invalid_key"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PL-API-03: POST with valid key, wait=false → 200, job created
# ---------------------------------------------------------------------------


def test_pipeline_scan_valid_key_wait_false(client, api_key, mock_run_image_scan):
    resp = client.post(
        "/api/pipeline/scan",
        json={**_SCAN_BODY, "wait": False},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert "status" in body


# ---------------------------------------------------------------------------
# PL-API-04: POST with valid key but unknown profile → 404
# ---------------------------------------------------------------------------


def test_pipeline_scan_unknown_profile_returns_404(client, api_key):
    resp = client.post(
        "/api/pipeline/scan",
        json={**_SCAN_BODY, "compliance_profile": "nonexistent-profile-xyz"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PL-API-05: Authorization: Bearer header accepted
# ---------------------------------------------------------------------------


def test_pipeline_scan_bearer_token_accepted(client, api_key, mock_run_image_scan):
    resp = client.post(
        "/api/pipeline/scan",
        json={**_SCAN_BODY, "wait": False},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PL-API-06: X-Api-Key header accepted
# ---------------------------------------------------------------------------


def test_pipeline_scan_x_api_key_header_accepted(client, api_key, mock_run_image_scan):
    resp = client.post(
        "/api/pipeline/scan",
        json={**_SCAN_BODY, "wait": False},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PL-API-07: GET /api/pipeline/scan/{id} with valid key → 200
# ---------------------------------------------------------------------------


def test_get_pipeline_scan_returns_200(client, api_key, mock_run_image_scan):
    # Create a job first
    create_resp = client.post(
        "/api/pipeline/scan",
        json={**_SCAN_BODY, "wait": False},
        headers={"X-Api-Key": api_key},
    )
    job_id = create_resp.json()["job_id"]

    resp = client.get(
        f"/api/pipeline/scan/{job_id}",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id


# ---------------------------------------------------------------------------
# PL-API-08: GET /api/pipeline/scan/{id} with no key → 401
# ---------------------------------------------------------------------------


def test_get_pipeline_scan_no_auth_returns_401(client):
    resp = client.get("/api/pipeline/scan/some-job-id")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PL-API-09: GET /api/pipeline/scans with valid key → 200, list
# ---------------------------------------------------------------------------


def test_list_pipeline_scans_returns_200(client, api_key):
    resp = client.get("/api/pipeline/scans", headers={"X-Api-Key": api_key})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# PL-API-10: POST /api/pipeline/verify/{id} completed, score 80% → passed=true
# ---------------------------------------------------------------------------


def test_verify_completed_scan_passes(client, api_key):
    job = AuditJob(
        job_type="image_scan",
        image_id="ami-verify",
        provider="aws",
        region="us-east-1",
        profile_name="test-ubuntu22-cis",
        target_host="ami-verify",
        status=AuditStatus.COMPLETE,
    )
    job.grade = "B"
    job.score_pct = 80.0
    job.severity_counts = {"critical": 0, "high": 0, "medium": 3, "low": 1}
    audit_mod._audit_jobs[job.id] = job

    resp = client.post(
        f"/api/pipeline/verify/{job.id}",
        params={"pass_threshold": 75.0, "severity_threshold": "high"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["passed"] is True


# ---------------------------------------------------------------------------
# PL-API-11: POST /api/pipeline/verify/{id} in-progress → 400
# ---------------------------------------------------------------------------


def test_verify_in_progress_scan_returns_400(client, api_key):
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

    resp = client.post(
        f"/api/pipeline/verify/{job.id}",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Extra: verify scan that fails threshold → passed=false
# ---------------------------------------------------------------------------


def test_verify_scan_below_threshold_is_not_passed(client, api_key):
    job = AuditJob(
        job_type="image_scan",
        image_id="ami-fail",
        provider="aws",
        region="us-east-1",
        profile_name="test-ubuntu22-cis",
        target_host="ami-fail",
        status=AuditStatus.COMPLETE,
    )
    job.grade = "D"
    job.score_pct = 50.0
    job.severity_counts = {"critical": 0, "high": 3, "medium": 8, "low": 2}
    audit_mod._audit_jobs[job.id] = job

    resp = client.post(
        f"/api/pipeline/verify/{job.id}",
        params={"pass_threshold": 75.0, "severity_threshold": "high"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["passed"] is False


# ---------------------------------------------------------------------------
# Extra: verify scan with high severity finding at default threshold → failed
# ---------------------------------------------------------------------------


def test_verify_scan_high_severity_fails_gate(client, api_key):
    job = AuditJob(
        job_type="image_scan",
        image_id="ami-high-sev",
        provider="aws",
        region="us-east-1",
        profile_name="test-ubuntu22-cis",
        target_host="ami-high-sev",
        status=AuditStatus.COMPLETE,
    )
    job.grade = "A"
    job.score_pct = 95.0
    job.severity_counts = {"critical": 0, "high": 1, "medium": 0, "low": 0}
    audit_mod._audit_jobs[job.id] = job

    resp = client.post(
        f"/api/pipeline/verify/{job.id}",
        params={"pass_threshold": 75.0, "severity_threshold": "high"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["passed"] is False


# ---------------------------------------------------------------------------
# PL-BUILD-01: POST /api/pipeline/build — no API key → 401
# ---------------------------------------------------------------------------


def test_pipeline_build_no_auth_returns_401(client):
    resp = client.post(
        "/api/pipeline/build",
        json={"profile_name": "test-ubuntu22-cis"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PL-BUILD-02: POST /api/pipeline/build — invalid key → 401
# ---------------------------------------------------------------------------


def test_pipeline_build_invalid_key_returns_401(client):
    resp = client.post(
        "/api/pipeline/build",
        json={"profile_name": "test-ubuntu22-cis"},
        headers={"X-Api-Key": "str_invalid_key_xyz"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PL-BUILD-03: POST /api/pipeline/build — unknown profile → 404
# ---------------------------------------------------------------------------


def test_pipeline_build_unknown_profile_returns_404(client, api_key):
    resp = client.post(
        "/api/pipeline/build",
        json={"profile_name": "no-such-profile"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PL-BUILD-04: POST /api/pipeline/build — wait=true → complete job with artifact_id
# ---------------------------------------------------------------------------


def test_pipeline_build_wait_true_returns_complete(client, api_key):
    from stratum.core.builder import BuildJob, BuildStatus
    from stratum.plugins.base_provider import ProviderResult

    async def _fake_run(profile, output_dir, job=None):
        if job is None:
            job = BuildJob(
                profile_name=profile.metadata.name,
                provider_name=profile.target.provider,
            )
        job.status = BuildStatus.COMPLETE
        job.result = ProviderResult(artifact_id="ami-ci-test-001", artifact_type="ami")
        from stratum.core import builder as bs

        bs._jobs[job.id] = job
        return job

    with patch("stratum.api.pipeline.build_service.run_build", side_effect=_fake_run):
        resp = client.post(
            "/api/pipeline/build",
            json={"profile_name": "test-ubuntu22-cis", "wait": True},
            headers={"X-Api-Key": api_key},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "complete"
    assert body["artifact_id"] == "ami-ci-test-001"


# ---------------------------------------------------------------------------
# PL-BUILD-05: POST /api/pipeline/build — wait=false → pending immediately
# ---------------------------------------------------------------------------


def test_pipeline_build_wait_false_returns_pending(client, api_key):
    # Patch run_build only — the real asyncio.create_task schedules the AsyncMock
    # coroutine, which the event loop consumes cleanly (no unawaited-coroutine warning).
    with patch("stratum.api.pipeline.build_service.run_build", new_callable=AsyncMock):
        resp = client.post(
            "/api/pipeline/build",
            json={"profile_name": "test-ubuntu22-cis", "wait": False},
            headers={"X-Api-Key": api_key},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "pending"


# ---------------------------------------------------------------------------
# PL-BUILD-06: GET /api/pipeline/build/{job_id} — no auth → 401
# ---------------------------------------------------------------------------


def test_get_pipeline_build_no_auth_returns_401(client):
    resp = client.get("/api/pipeline/build/some-job-id")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PL-BUILD-07: GET /api/pipeline/build/{job_id} — unknown id → 404
# ---------------------------------------------------------------------------


def test_get_pipeline_build_job_not_found(client, api_key):
    resp = client.get(
        "/api/pipeline/build/nonexistent-job-id",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PL-BUILD-08: GET /api/pipeline/build/{job_id} — valid → returns job JSON
# ---------------------------------------------------------------------------


def test_get_pipeline_build_job_returns_status(client, api_key):
    from stratum.core import builder as bs
    from stratum.core.builder import BuildJob, BuildStatus
    from stratum.plugins.base_provider import ProviderResult

    job = BuildJob(profile_name="test-ubuntu22-cis", provider_name="aws")
    job.status = BuildStatus.COMPLETE
    job.result = ProviderResult(artifact_id="ami-abc-999", artifact_type="ami")
    bs._jobs[job.id] = job

    resp = client.get(
        f"/api/pipeline/build/{job.id}",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job.id
    assert body["status"] == "complete"
    assert body["artifact_id"] == "ami-abc-999"


# ---------------------------------------------------------------------------
# PL-INLINE-01: POST /api/pipeline/build with blueprint_yaml — valid inline YAML
# ---------------------------------------------------------------------------

_INLINE_BLUEPRINT_YAML = """\
stratum_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: inline-ci-profile
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  region: us-east-1
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""


def test_pipeline_build_inline_yaml_returns_200(client, api_key):
    from stratum.core.builder import BuildJob, BuildStatus
    from stratum.plugins.base_provider import ProviderResult

    async def _fake_run(profile, output_dir, job=None):
        if job is None:
            from stratum.core import builder as bs

            job = BuildJob(profile_name=profile.metadata.name, provider_name=profile.target.provider)
            bs._jobs[job.id] = job
        job.status = BuildStatus.COMPLETE
        job.result = ProviderResult(artifact_id="ami-inline-001", artifact_type="ami")

    with patch("stratum.api.pipeline.build_service.run_build", side_effect=_fake_run):
        resp = client.post(
            "/api/pipeline/build",
            json={"blueprint_yaml": _INLINE_BLUEPRINT_YAML, "wait": True},
            headers={"X-Api-Key": api_key},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body["profile_name"] == "inline-ci-profile"


def test_pipeline_build_inline_yaml_takes_precedence_over_profile_name(client, api_key):
    from stratum.core.builder import BuildJob, BuildStatus
    from stratum.plugins.base_provider import ProviderResult

    async def _fake_run(profile, output_dir, job=None):
        if job is None:
            from stratum.core import builder as bs

            job = BuildJob(profile_name=profile.metadata.name, provider_name=profile.target.provider)
            bs._jobs[job.id] = job
        job.status = BuildStatus.COMPLETE
        job.result = ProviderResult(artifact_id="ami-inline-002", artifact_type="ami")

    with patch("stratum.api.pipeline.build_service.run_build", side_effect=_fake_run):
        resp = client.post(
            "/api/pipeline/build",
            json={
                "profile_name": "test-ubuntu22-cis",
                "blueprint_yaml": _INLINE_BLUEPRINT_YAML,
                "wait": True,
            },
            headers={"X-Api-Key": api_key},
        )

    assert resp.status_code == 200
    assert resp.json()["profile_name"] == "inline-ci-profile"


def test_pipeline_build_inline_yaml_invalid_schema_returns_422(client, api_key):
    resp = client.post(
        "/api/pipeline/build",
        json={
            "blueprint_yaml": "kind: NotAProfile\nmetadata:\n  name: bad\n",
            "wait": False,
        },
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 422


def test_pipeline_build_neither_profile_nor_yaml_returns_422(client, api_key):
    resp = client.post(
        "/api/pipeline/build",
        json={"wait": False},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 422
