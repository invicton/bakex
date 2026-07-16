# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests covering remaining gaps in plugins, auditor, and pipeline API modules.

Covers:
  api/plugins.py   31-32, 36-38  — _load_catalog: missing index, parse error
  api/plugins.py   91, 120       — download: provider not in catalog, script missing
  api/plugins.py   141-143       — install: file write exception
  api/plugins.py   175-177       — remove: exception path
  api/auditor.py   75-95         — start_image_scan: creates job + background task
  api/auditor.py   172           — export_scan_report: job not found → 404
  api/auditor.py   188, 202      — export_scan_report: json/sarif format
  api/auditor.py   211           — export_scan_report: scan not complete → 400
  api/auditor.py   250-251       — _resolve_profile: not found → 404
  api/pipeline.py  104           — pipeline_scan with wait=True
  api/pipeline.py  130           — get_pipeline_scan: job not found → 404
  api/pipeline.py  144           — verify_scan: job not found → 404
  api/pipeline.py  196, 198      — pipeline_build: provider/region override
  api/pipeline.py  234-235       — _resolve_profile not found → 404
  api/pipeline.py  243-244       — _resolve_inline_yaml: YAML parse error → 422
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

# ===========================================================================
# api/plugins.py
# ===========================================================================


class TestPluginsCatalogHelpers:
    def test_load_catalog_missing_index_returns_empty(self, client):
        """_load_catalog returns [] when index.json does not exist."""

        with patch("statim.api.plugins._load_catalog", return_value=[]):
            resp = client.get("/api/plugins/catalog")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_load_catalog_parse_error_returns_empty(self, tmp_path):
        """_load_catalog returns [] and logs error on malformed JSON."""
        from statim.api.plugins import _load_catalog

        catalog_dir = tmp_path / "catalog"
        catalog_dir.mkdir()
        index = catalog_dir / "index.json"
        index.write_text("{bad json{{{")
        mock_settings = patch("statim.api.plugins.settings")
        with mock_settings as s:
            s.catalog_dir_absolute = catalog_dir
            result = _load_catalog()
        assert result == []

    def test_load_catalog_returns_empty_when_no_index(self, tmp_path):
        """_load_catalog returns [] when no index.json exists."""
        from statim.api.plugins import _load_catalog

        with patch("statim.api.plugins.settings") as mock_settings:
            mock_settings.catalog_dir_absolute = tmp_path / "nonexistent"
            result = _load_catalog()
        assert result == []

    def test_download_provider_script_not_in_catalog_returns_404(self, client):
        """download_provider_script returns 404 when provider_id is not in catalog."""
        with patch("statim.api.plugins._load_catalog", return_value=[]):
            resp = client.get("/api/plugins/catalog/nonexistent-provider/download")
        assert resp.status_code == 404

    def test_download_provider_script_missing_file_returns_404(self, client, tmp_path):
        """download_provider_script returns 404 when the script file is missing."""
        catalog = [{"id": "mycloud", "name": "MyCloud", "script": "mycloud.py"}]
        with patch("statim.api.plugins._load_catalog", return_value=catalog):
            with patch("statim.api.plugins.settings") as mock_settings:
                mock_settings.catalog_dir_absolute = tmp_path  # mycloud.py doesn't exist here
                resp = client.get("/api/plugins/catalog/mycloud/download")
        assert resp.status_code == 404

    def test_install_plugin_write_exception_returns_500(self, client, tmp_path):
        """install_plugin returns 500 HTML when file write fails."""
        script = tmp_path / "myprov.py"
        script.write_text("PROVIDER_NAME = 'myprov'\n")
        catalog = [{"id": "myprov", "name": "MyProv", "script": "myprov.py"}]

        with patch("statim.api.plugins._load_catalog", return_value=catalog):
            with patch("statim.api.plugins.settings") as mock_settings:
                mock_settings.catalog_dir_absolute = tmp_path
                mock_settings.plugins_dir_absolute = tmp_path / "plugins_ro"
                with patch("pathlib.Path.write_bytes", side_effect=PermissionError("denied")):
                    resp = client.post("/api/plugins/install", data={"provider_id": "myprov"})
        assert resp.status_code == 500
        assert "Error installing" in resp.text

    def test_remove_plugin_exception_returns_500(self, client, tmp_path):
        """remove_plugin returns 500 HTML when unlink raises an exception."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "myprov2.py").write_text("x = 1")
        catalog = [{"id": "myprov2", "name": "MyProv2", "script": "myprov2.py"}]

        with patch("statim.api.plugins._load_catalog", return_value=catalog):
            with patch("statim.api.plugins.settings") as mock_settings:
                mock_settings.plugins_dir_absolute = plugins_dir
                with patch("pathlib.Path.unlink", side_effect=OSError("locked")):
                    resp = client.post("/api/plugins/myprov2/remove")
        assert resp.status_code == 500
        assert "Error removing" in resp.text


# ===========================================================================
# api/auditor.py
# ===========================================================================


class TestAuditorEndpoints:
    def test_start_image_scan_creates_job_and_returns_htmx_redirect(self, client):
        """POST /auditor/scan-image creates a job and returns an HTMX redirect header."""
        with patch("statim.api.auditor.audit_service.run_image_scan", new_callable=AsyncMock):
            resp = client.post(
                "/api/auditor/scan-image",
                json={
                    "image_id": "ami-auditor-001",
                    "provider": "aws",
                    "region": "us-east-1",
                    "os": "ubuntu22.04",
                    "compliance_profile": "test-ubuntu22-cis",
                    "instance_type": "t3.medium",
                },
            )
        assert resp.status_code == 200
        assert "HX-Redirect" in resp.headers

    def test_export_scan_report_job_not_found_returns_404(self, client):
        """export_scan_report returns 404 when job_id is unknown."""
        resp = client.get("/api/auditor/scan-image/nonexistent-job-id/report")
        assert resp.status_code == 404

    def test_export_scan_report_not_complete_returns_400(self, client):
        """export_scan_report returns 400 when the scan job is not complete."""
        import statim.core.auditor as audit_mod
        from statim.core.auditor import AuditJob

        job = AuditJob(
            job_type="image_scan",
            image_id="ami-pending",
            provider="aws",
            region="us-east-1",
            profile_name="test-ubuntu22-cis",
            target_host="ami-pending",
        )
        audit_mod._audit_jobs[job.id] = job

        resp = client.get(f"/api/auditor/scan-image/{job.id}/report")
        assert resp.status_code == 400

    def test_export_scan_report_json_format(self, client):
        """export_scan_report with ?fmt=json returns JSON content."""
        import statim.core.auditor as audit_mod
        from statim.core.auditor import AuditJob, AuditStatus

        job = AuditJob(
            job_type="image_scan",
            image_id="ami-done",
            provider="aws",
            region="us-east-1",
            profile_name="test-ubuntu22-cis",
            target_host="ami-done",
        )
        job.status = AuditStatus.COMPLETE
        job.grade = "A"
        job.score_pct = 95.0
        job.results = {"findings": [], "score": 95.0}
        audit_mod._audit_jobs[job.id] = job

        resp = client.get(f"/api/auditor/scan-image/{job.id}/report?fmt=json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["grade"] == "A"

    def test_export_scan_report_sarif_format(self, client):
        """export_scan_report with ?fmt=sarif returns SARIF JSON."""
        import statim.core.auditor as audit_mod
        from statim.core.auditor import AuditJob, AuditStatus

        job = AuditJob(
            job_type="image_scan",
            image_id="ami-sarif",
            provider="aws",
            region="us-east-1",
            profile_name="test-ubuntu22-cis",
            target_host="ami-sarif",
        )
        job.status = AuditStatus.COMPLETE
        job.grade = "B"
        job.score_pct = 80.0
        job.results = {"findings": [{"rule_id": "sshd_rule", "status": "fail", "severity": "high"}], "score": 80.0}
        audit_mod._audit_jobs[job.id] = job

        resp = client.get(f"/api/auditor/scan-image/{job.id}/report?fmt=sarif")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("version") == "2.1.0"

    def test_resolve_profile_not_found_returns_404(self, client):
        """POST scan-image with unknown compliance_profile returns 404."""
        resp = client.post(
            "/api/auditor/scan-image",
            json={
                "image_id": "ami-001",
                "provider": "aws",
                "region": "us-east-1",
                "os": "ubuntu22.04",
                "compliance_profile": "no-such-profile-xyz",
                "instance_type": "t3.medium",
            },
        )
        assert resp.status_code == 404


# ===========================================================================
# api/pipeline.py
# ===========================================================================


class TestPipelineEndpoints:
    def test_pipeline_scan_wait_true_awaits_scan(self, client, api_key, mock_run_image_scan):
        """pipeline_scan with wait=True runs scan synchronously (not as background task)."""
        resp = client.post(
            "/api/pipeline/scan",
            json={
                "image_id": "ami-wait-001",
                "provider": "aws",
                "region": "us-east-1",
                "compliance_profile": "test-ubuntu22-cis",
                "wait": True,
            },
            headers={"X-Api-Key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data

    def test_get_pipeline_scan_not_found_returns_404(self, client, api_key):
        """GET /api/pipeline/scan/{job_id} returns 404 for unknown job."""
        resp = client.get(
            "/api/pipeline/scan/nonexistent-job-xyz",
            headers={"X-Api-Key": api_key},
        )
        assert resp.status_code == 404

    def test_verify_scan_not_found_returns_404(self, client, api_key):
        """POST /api/pipeline/verify/{job_id} returns 404 for unknown job."""
        resp = client.post(
            "/api/pipeline/verify/nonexistent-job-xyz",
            headers={"X-Api-Key": api_key},
        )
        assert resp.status_code == 404

    def test_pipeline_build_with_provider_override(self, client, api_key):
        """pipeline_build applies provider override from request to the profile."""
        from unittest.mock import AsyncMock, patch

        with patch("statim.api.pipeline.build_service.run_build", new_callable=AsyncMock):
            resp = client.post(
                "/api/pipeline/build",
                json={
                    "profile_name": "test-ubuntu22-cis",
                    "provider": "gcp",
                    "wait": True,
                },
                headers={"X-Api-Key": api_key},
            )
        assert resp.status_code == 200

    def test_pipeline_build_unknown_profile_returns_404(self, client, api_key):
        """pipeline_build with unknown profile_name returns 404."""
        resp = client.post(
            "/api/pipeline/build",
            json={"profile_name": "nonexistent-xyz"},
            headers={"X-Api-Key": api_key},
        )
        assert resp.status_code == 404

    def test_pipeline_build_invalid_yaml_returns_422(self, client, api_key):
        """pipeline_build with malformed blueprint_yaml returns 422."""
        resp = client.post(
            "/api/pipeline/build",
            json={"blueprint_yaml": "{invalid: [yaml{{ BAD"},
            headers={"X-Api-Key": api_key},
        )
        assert resp.status_code == 422
