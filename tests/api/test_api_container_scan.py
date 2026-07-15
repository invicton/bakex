# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Container image scan API — POST /api/auditor/scan-container."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def test_scan_container_endpoint_backgrounds_job(client):
    # Patch the orchestration so the endpoint test does no real scan / network I/O.
    with patch("invicton.api.auditor.audit_service.run_container_scan_job", new=AsyncMock()) as mock_job:
        resp = client.post(
            "/api/auditor/scan-container",
            json={"image": "ubuntu:22.04", "os": "ubuntu22.04", "tier": "cis-l1"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "job_id" in body and body["status"] == "pending"

    from invicton.core import auditor

    job = auditor._audit_jobs.get(body["job_id"])
    assert job is not None
    assert job.job_type == "container_scan"
    assert job.image_id == "ubuntu:22.04"
    mock_job.assert_called_once()  # the scan was scheduled


def test_scan_container_endpoint_validates_missing_fields(client):
    resp = client.post("/api/auditor/scan-container", json={"image": "ubuntu:22.04"})
    assert resp.status_code == 422  # missing required os
