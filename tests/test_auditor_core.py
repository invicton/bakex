# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Core auditor logic unit tests — job store, score helpers, and image scan."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import bakex.core.auditor as auditor_mod
from bakex.core.auditor import (
    AuditJob,
    AuditStatus,
    _severity_counts,
    get_audit,
    list_audits,
    load_jobs,
    score_to_grade,
)


@pytest.fixture(autouse=True)
def _clean_jobs():
    """Isolate the in-memory job store for every test."""
    auditor_mod._audit_jobs.clear()
    yield
    auditor_mod._audit_jobs.clear()


# ---------------------------------------------------------------------------
# score_to_grade — boundary values (already tested in pipeline, but also here
# since _severity_counts and score_to_grade live in auditor.py)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,grade",
    [
        (100.0, "A"),
        (90.0, "A"),
        (89.9, "B"),
        (75.0, "B"),
        (74.9, "C"),
        (60.0, "C"),
        (59.9, "D"),
        (40.0, "D"),
        (39.9, "F"),
        (0.0, "F"),
    ],
)
def test_score_to_grade_boundaries(score, grade):
    assert score_to_grade(score) == grade


# ---------------------------------------------------------------------------
# _severity_counts — tally failed rules by severity
# ---------------------------------------------------------------------------


def test_severity_counts_empty():
    counts = _severity_counts({})
    assert counts == {"critical": 0, "high": 0, "medium": 0, "low": 0}


def test_severity_counts_only_passes():
    results = {
        "rules": [
            {"result": "pass", "severity": "high"},
            {"result": "pass", "severity": "critical"},
        ]
    }
    counts = _severity_counts(results)
    assert counts == {"critical": 0, "high": 0, "medium": 0, "low": 0}


def test_severity_counts_mixed():
    results = {
        "rules": [
            {"result": "fail", "severity": "critical"},
            {"result": "fail", "severity": "high"},
            {"result": "fail", "severity": "high"},
            {"result": "fail", "severity": "medium"},
            {"result": "pass", "severity": "critical"},
            {"result": "fail", "severity": "low"},
        ]
    }
    counts = _severity_counts(results)
    assert counts["critical"] == 1
    assert counts["high"] == 2
    assert counts["medium"] == 1
    assert counts["low"] == 1


def test_severity_counts_unknown_severity_ignored():
    results = {
        "rules": [
            {"result": "fail", "severity": "unknown_level"},
        ]
    }
    counts = _severity_counts(results)
    assert sum(counts.values()) == 0


def test_severity_counts_case_insensitive():
    results = {
        "rules": [
            {"result": "fail", "severity": "HIGH"},
            {"result": "fail", "severity": "Medium"},
        ]
    }
    counts = _severity_counts(results)
    assert counts["high"] == 1
    assert counts["medium"] == 1


# ---------------------------------------------------------------------------
# Job store — get_audit / list_audits
# ---------------------------------------------------------------------------


def test_get_audit_returns_job():
    job = AuditJob(target_host="10.0.0.1", profile_name="test")
    auditor_mod._audit_jobs[job.id] = job
    assert get_audit(job.id) is job


def test_get_audit_nonexistent_returns_none():
    assert get_audit("no-such-id") is None


def test_list_audits_sorted_newest_first():
    j1 = AuditJob(created_at=datetime(2026, 1, 1, tzinfo=UTC))
    j2 = AuditJob(created_at=datetime(2026, 1, 2, tzinfo=UTC))
    j3 = AuditJob(created_at=datetime(2026, 1, 3, tzinfo=UTC))
    for j in (j1, j2, j3):
        auditor_mod._audit_jobs[j.id] = j
    result = list_audits()
    assert result[0].id == j3.id
    assert result[-1].id == j1.id


def test_list_audits_empty():
    assert list_audits() == []


# ---------------------------------------------------------------------------
# load_jobs — deserialise from disk
# ---------------------------------------------------------------------------


def test_load_jobs_populates_store(tmp_path, monkeypatch):
    jobs_file = tmp_path / "audit_jobs.json"
    now = datetime.now(UTC).isoformat()
    data = {
        "abc-123": {
            "id": "abc-123",
            "job_type": "image_scan",
            "target_host": "ami-00001",
            "profile_name": "test",
            "status": "complete",
            "image_id": "ami-00001",
            "provider": "aws",
            "region": "us-east-1",
            "grade": "A",
            "score_pct": 95.0,
            "severity_counts": {"critical": 0, "high": 0, "medium": 1, "low": 2},
            "results": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
    }
    jobs_file.write_text(json.dumps(data))
    monkeypatch.setattr(auditor_mod, "_JOBS_FILE", jobs_file)
    load_jobs()
    job = get_audit("abc-123")
    assert job is not None
    assert job.status == AuditStatus.COMPLETE
    assert job.grade == "A"
    assert job.score_pct == 95.0


def test_load_jobs_missing_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(auditor_mod, "_JOBS_FILE", tmp_path / "nonexistent.json")
    load_jobs()  # must not raise
    assert list_audits() == []


def test_load_jobs_corrupted_file_is_handled(tmp_path, monkeypatch):
    jobs_file = tmp_path / "audit_jobs.json"
    jobs_file.write_text("not valid json!!")
    monkeypatch.setattr(auditor_mod, "_JOBS_FILE", jobs_file)
    load_jobs()  # must not raise
    assert list_audits() == []


# ---------------------------------------------------------------------------
# run_image_scan — cloud path (handles_full_lifecycle=True)
# ---------------------------------------------------------------------------


def _make_minimal_profile():
    from bakex.core.blueprint import ComplianceProfile

    return ComplianceProfile.model_validate(
        {
            "bakex_version": "0.1.0",
            "kind": "ComplianceProfile",
            "metadata": {"name": "test-profile", "version": "1.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-0"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
            "controls": {},
        }
    )


@pytest.mark.anyio
async def test_run_image_scan_unknown_provider_fails():
    from bakex.plugins.registry import registry

    with patch.object(registry, "get", return_value=None):
        job = await auditor_mod.run_image_scan(
            image_id="ami-00001",
            provider_name="nonexistent",
            region="us-east-1",
            profile=_make_minimal_profile(),
            instance_type="t3.micro",
            output_dir=Path("/tmp"),
        )
    assert job.status == AuditStatus.FAILED
    assert "not found" in job.error


@pytest.mark.anyio
async def test_run_image_scan_cloud_path_success(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = True
    mock_provider = MagicMock()
    mock_provider.scan_image.return_value = {"raw_xml": ""}
    mock_provider_cls.return_value = mock_provider

    mock_results = {
        "score": 85.0,
        "rules": [{"result": "fail", "severity": "medium"}],
    }

    with patch.object(registry, "get", return_value=mock_provider_cls):
        with patch("bakex.core.parser.SCAPParser.parse_report", return_value=mock_results):
            job = await auditor_mod.run_image_scan(
                image_id="ami-00001",
                provider_name="aws",
                region="us-east-1",
                profile=_make_minimal_profile(),
                instance_type="t3.micro",
                output_dir=tmp_path,
            )

    assert job.status == AuditStatus.COMPLETE
    assert job.grade == "B"
    assert job.score_pct == 85.0
    assert job.severity_counts["medium"] == 1


@pytest.mark.anyio
async def test_run_image_scan_cloud_path_exception_marks_failed(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = True
    mock_provider = MagicMock()
    mock_provider.scan_image.side_effect = RuntimeError("connection timeout")
    mock_provider_cls.return_value = mock_provider

    with patch.object(registry, "get", return_value=mock_provider_cls):
        job = await auditor_mod.run_image_scan(
            image_id="ami-00001",
            provider_name="aws",
            region="us-east-1",
            profile=_make_minimal_profile(),
            instance_type="t3.micro",
            output_dir=tmp_path,
        )

    assert job.status == AuditStatus.FAILED
    assert "connection timeout" in job.error


@pytest.mark.anyio
async def test_run_image_scan_null_score_no_grade(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = True
    mock_provider = MagicMock()
    mock_provider.scan_image.return_value = {"raw_xml": ""}
    mock_provider_cls.return_value = mock_provider

    mock_results = {"score": None, "rules": []}

    with patch.object(registry, "get", return_value=mock_provider_cls):
        with patch("bakex.core.parser.SCAPParser.parse_report", return_value=mock_results):
            job = await auditor_mod.run_image_scan(
                image_id="ami-00001",
                provider_name="aws",
                region="us-east-1",
                profile=_make_minimal_profile(),
                instance_type="t3.micro",
                output_dir=tmp_path,
            )

    assert job.status == AuditStatus.COMPLETE
    assert job.grade is None
    assert job.score_pct is None


# ---------------------------------------------------------------------------
# run_image_scan — SSH-based path (handles_full_lifecycle=False)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_image_scan_ssh_path_success(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = False
    mock_provider = MagicMock()
    mock_provider.provision.return_value = "i-temp-1234"
    mock_provider_cls.return_value = mock_provider

    fake_arf = tmp_path / "results-arf.xml"
    fake_arf.write_text("<arf/>")

    mock_results = {"score": 78.0, "rules": [{"result": "fail", "severity": "low"}]}

    with patch.object(registry, "get", return_value=mock_provider_cls):
        with patch("bakex.core.auditor.oscap_scanner.run_scan", return_value=fake_arf):
            with patch("bakex.core.auditor.parse_arf", return_value=mock_results):
                job = await auditor_mod.run_image_scan(
                    image_id="ami-ssh",
                    provider_name="local",
                    region="",
                    profile=_make_minimal_profile(),
                    instance_type="t3.micro",
                    output_dir=tmp_path,
                )

    assert job.status == AuditStatus.COMPLETE
    assert job.grade == "B"
    assert job.score_pct == 78.0
    # Teardown should have been called
    mock_provider_cls.return_value.teardown.assert_called_once_with("i-temp-1234")


@pytest.mark.anyio
async def test_run_image_scan_ssh_path_teardown_on_failure(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = False
    mock_provider = MagicMock()
    mock_provider.provision.return_value = "i-temp-fail"
    mock_provider_cls.return_value = mock_provider

    with patch.object(registry, "get", return_value=mock_provider_cls):
        with patch("bakex.core.auditor.oscap_scanner.run_scan", side_effect=RuntimeError("scan failed")):
            job = await auditor_mod.run_image_scan(
                image_id="ami-fail",
                provider_name="local",
                region="",
                profile=_make_minimal_profile(),
                instance_type="t3.micro",
                output_dir=tmp_path,
            )

    assert job.status == AuditStatus.FAILED
    assert "scan failed" in job.error
    # Teardown still called even on failure
    mock_provider_cls.return_value.teardown.assert_called_once_with("i-temp-fail")


@pytest.mark.anyio
async def test_run_image_scan_ssh_path_teardown_exception_ignored(tmp_path):
    """Teardown failure in finally block should not mask the original error."""
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = False
    mock_provider = MagicMock()
    mock_provider.provision.return_value = "i-temp-xyz"
    mock_provider_cls.return_value = mock_provider
    # Make teardown raise
    mock_provider_cls.return_value.teardown.side_effect = RuntimeError("teardown boom")

    with patch.object(registry, "get", return_value=mock_provider_cls):
        with patch("bakex.core.auditor.oscap_scanner.run_scan", side_effect=RuntimeError("scan err")):
            job = await auditor_mod.run_image_scan(
                image_id="ami-xyz",
                provider_name="local",
                region="",
                profile=_make_minimal_profile(),
                instance_type="t3.micro",
                output_dir=tmp_path,
            )

    assert job.status == AuditStatus.FAILED
    assert "scan err" in job.error


# ---------------------------------------------------------------------------
# run_audit — live host scan
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_audit_local_path_success(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = False
    with patch.object(registry, "get", return_value=mock_provider_cls):
        fake_arf = tmp_path / "scan.xml"
        fake_arf.write_text("<arf/>")
        mock_results = {"score": 91.0, "rules": []}

        with patch("bakex.core.auditor.oscap_scanner.run_scan", return_value=fake_arf):
            with patch("bakex.core.auditor.parse_arf", return_value=mock_results):
                job = await auditor_mod.run_audit(
                    profile=_make_minimal_profile(),
                    target_host="10.0.0.1",
                    ssh_user="ubuntu",
                    output_dir=tmp_path,
                )

    assert job.status == AuditStatus.COMPLETE
    assert job.target_host == "10.0.0.1"
    assert job.arf_path == fake_arf


@pytest.mark.anyio
async def test_run_audit_local_path_with_baseline(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = False
    with patch.object(registry, "get", return_value=mock_provider_cls):
        fake_arf = tmp_path / "scan.xml"
        fake_arf.write_text("<arf/>")
        baseline_arf = tmp_path / "baseline.xml"
        baseline_arf.write_text("<arf/>")

        mock_results = {"score": 80.0, "rules": []}
        mock_delta = {"added": [], "removed": [], "changed": []}

        with patch("bakex.core.auditor.oscap_scanner.run_scan", return_value=fake_arf):
            with patch("bakex.core.auditor.parse_arf", return_value=mock_results):
                with patch("bakex.core.auditor.compute_delta", return_value=mock_delta):
                    job = await auditor_mod.run_audit(
                        profile=_make_minimal_profile(),
                        target_host="10.0.0.2",
                        ssh_user="root",
                        output_dir=tmp_path,
                        baseline_arf=baseline_arf,
                    )

    assert job.status == AuditStatus.COMPLETE
    assert job.delta == mock_delta


@pytest.mark.anyio
async def test_run_audit_cloud_path_success(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = True
    mock_provider = MagicMock()
    mock_provider.audit.return_value = {"raw_xml": ""}
    mock_provider_cls.return_value = mock_provider

    mock_results = {"score": 88.0, "rules": []}

    with patch.object(registry, "get", return_value=mock_provider_cls):
        with patch("bakex.core.parser.SCAPParser.parse_report", return_value=mock_results):
            job = await auditor_mod.run_audit(
                profile=_make_minimal_profile(),
                target_host="i-cloud-001",
                ssh_user="ubuntu",
                output_dir=tmp_path,
            )

    assert job.status == AuditStatus.COMPLETE
    mock_provider.audit.assert_called_once_with("i-cloud-001", _make_minimal_profile())


@pytest.mark.anyio
async def test_run_audit_exception_marks_failed(tmp_path):
    from bakex.plugins.registry import registry

    mock_provider_cls = MagicMock()
    mock_provider_cls.handles_full_lifecycle = False
    with patch.object(registry, "get", return_value=mock_provider_cls):
        with patch("bakex.core.auditor.oscap_scanner.run_scan", side_effect=RuntimeError("oscap not found")):
            job = await auditor_mod.run_audit(
                profile=_make_minimal_profile(),
                target_host="10.0.0.3",
                ssh_user="ubuntu",
                output_dir=tmp_path,
            )

    assert job.status == AuditStatus.FAILED
    assert "oscap not found" in job.error


# ---------------------------------------------------------------------------
# _persist_jobs — exception path
# ---------------------------------------------------------------------------


def test_persist_jobs_exception_is_warned(tmp_path, monkeypatch, caplog):
    """Write failure should log a warning, not crash."""
    import logging

    # Point to a dir as the jobs file (so write will fail)
    monkeypatch.setattr(auditor_mod, "_JOBS_FILE", tmp_path)
    job = AuditJob(target_host="h", profile_name="p")
    auditor_mod._audit_jobs[job.id] = job

    with caplog.at_level(logging.WARNING, logger="bakex.core.auditor"):
        auditor_mod._persist_jobs()

    assert any("Could not persist" in r.message for r in caplog.records)
