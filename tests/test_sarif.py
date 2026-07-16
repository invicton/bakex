# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for SARIF 2.1.0 export — Phase 1 TDD red run."""

from __future__ import annotations

import pytest

from bakex.api.auditor import _to_sarif
from bakex.core.auditor import AuditJob, AuditStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(findings: list[dict] | None = None, rules: list[dict] | None = None) -> AuditJob:
    """Build a completed AuditJob with the given findings or raw rules."""
    job = AuditJob(
        job_type="image_scan",
        image_id="ami-test-001",
        provider="aws",
        region="us-east-1",
        profile_name="ubuntu22-cis-l1",
        target_host="ami-test-001",
        status=AuditStatus.COMPLETE,
    )
    job.grade = "B"
    job.score_pct = 82.5
    job.severity_counts = {"critical": 0, "high": 2, "medium": 5, "low": 3}
    if findings is not None:
        job.results = {"findings": findings, "score": 82.5}
    elif rules is not None:
        job.results = {"rules": rules, "score": 82.5}
    else:
        job.results = {"findings": [], "score": 82.5}
    return job


def _finding(rule_id: str, status: str = "fail", severity: str = "high", title: str = "") -> dict:
    return {"rule_id": rule_id, "status": status, "severity": severity, "title": title or rule_id}


# ---------------------------------------------------------------------------
# SA-01: output is valid SARIF 2.1.0
# ---------------------------------------------------------------------------


def test_sarif_version_and_schema():
    job = _make_job(findings=[_finding("accounts_min_age")])
    sarif = _to_sarif(job)
    assert sarif["version"] == "2.1.0", "SARIF version must be '2.1.0'"
    assert "$schema" in sarif, "SARIF output must include '$schema' key"
    assert "runs" in sarif, "SARIF output must include 'runs' key"
    assert len(sarif["runs"]) == 1


# ---------------------------------------------------------------------------
# SA-02: only 'fail' findings are exported
# ---------------------------------------------------------------------------


def test_only_fail_findings_exported():
    findings = [
        _finding("rule_pass", status="pass"),
        _finding("rule_fail", status="fail"),
        _finding("rule_exception", status="approved_exception"),
    ]
    job = _make_job(findings=findings)
    sarif = _to_sarif(job)
    result_ids = [r["ruleId"] for r in sarif["runs"][0]["results"]]
    assert "rule_fail" in result_ids
    assert "rule_pass" not in result_ids, "pass findings must not appear in SARIF results"


# ---------------------------------------------------------------------------
# SA-03: approved_exception findings excluded
# ---------------------------------------------------------------------------


def test_approved_exception_excluded():
    findings = [
        _finding("excepted_rule", status="approved_exception", severity="high"),
        _finding("real_fail", status="fail", severity="medium"),
    ]
    job = _make_job(findings=findings)
    sarif = _to_sarif(job)
    result_ids = [r["ruleId"] for r in sarif["runs"][0]["results"]]
    assert "excepted_rule" not in result_ids, "approved_exception must be excluded from SARIF"
    assert "real_fail" in result_ids


# ---------------------------------------------------------------------------
# SA-04: severity mapped correctly to SARIF level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "severity,expected_level",
    [
        ("critical", "error"),
        ("high", "error"),
        ("medium", "warning"),
        ("low", "note"),
    ],
)
def test_severity_mapped_to_sarif_level(severity, expected_level):
    job = _make_job(findings=[_finding("some_rule", status="fail", severity=severity)])
    sarif = _to_sarif(job)
    result = sarif["runs"][0]["results"][0]
    assert result["level"] == expected_level, (
        f"severity '{severity}' must map to SARIF level '{expected_level}', got '{result['level']}'"
    )


# ---------------------------------------------------------------------------
# SA-05: duplicate rule IDs deduplicated in rules list
# ---------------------------------------------------------------------------


def test_duplicate_rule_ids_deduplicated():
    findings = [
        _finding("duplicate_rule", status="fail"),
        _finding("duplicate_rule", status="fail"),
    ]
    job = _make_job(findings=findings)
    sarif = _to_sarif(job)
    driver_rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    rule_ids = [r["id"] for r in driver_rules]
    assert len(rule_ids) == len(set(rule_ids)), "Duplicate rule IDs must be deduplicated in driver.rules"


# ---------------------------------------------------------------------------
# SA-06: ARF-format results (rules list) also exported correctly
# ---------------------------------------------------------------------------


def test_arf_format_rules_exported():
    rules = [
        {"id": "arf_rule_fail", "result": "fail", "severity": "high", "title": "ARF rule"},
        {"id": "arf_rule_pass", "result": "pass", "severity": "low", "title": "Passing rule"},
    ]
    job = _make_job(rules=rules)
    sarif = _to_sarif(job)
    result_ids = [r["ruleId"] for r in sarif["runs"][0]["results"]]
    assert "arf_rule_fail" in result_ids, "Failed ARF-format rules must appear in SARIF"
    assert "arf_rule_pass" not in result_ids, "Passing ARF-format rules must not appear"


# ---------------------------------------------------------------------------
# SA-07: empty findings → valid SARIF with empty results list
# ---------------------------------------------------------------------------


def test_empty_findings_produces_valid_sarif():
    job = _make_job(findings=[])
    sarif = _to_sarif(job)
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"] == [], "Empty findings must produce empty SARIF results"


# ---------------------------------------------------------------------------
# Extra: run properties include scan metadata
# ---------------------------------------------------------------------------


def test_sarif_run_properties_contain_metadata():
    job = _make_job(findings=[_finding("rule_1")])
    sarif = _to_sarif(job)
    props = sarif["runs"][0].get("properties", {})
    assert "grade" in props, "SARIF run properties must include grade"
    assert "score_pct" in props, "SARIF run properties must include score_pct"
    assert "image_id" in props, "SARIF run properties must include image_id"


# ---------------------------------------------------------------------------
# Extra: tool driver name and version present
# ---------------------------------------------------------------------------


def test_sarif_tool_driver_fields():
    job = _make_job(findings=[])
    sarif = _to_sarif(job)
    driver = sarif["runs"][0]["tool"]["driver"]
    assert "name" in driver
    assert "version" in driver
    assert "informationUri" in driver


# ---------------------------------------------------------------------------
# Extra: result location uses image_id as artifact URI
# ---------------------------------------------------------------------------


def test_sarif_result_location_uses_image_id():
    job = _make_job(findings=[_finding("location_rule", status="fail")])
    sarif = _to_sarif(job)
    result = sarif["runs"][0]["results"][0]
    uri = result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert uri == "ami-test-001", f"Location URI must be the image_id, got '{uri}'"


# ---------------------------------------------------------------------------
# Extra: unknown severity defaults to 'warning' not exception
# ---------------------------------------------------------------------------


def test_unknown_severity_defaults_gracefully():
    findings = [{"rule_id": "unknown_sev_rule", "status": "fail", "severity": "unknown_level", "title": ""}]
    job = _make_job(findings=findings)
    sarif = _to_sarif(job)  # must not raise
    result = sarif["runs"][0]["results"][0]
    assert result["level"] in ("error", "warning", "note"), (
        f"Unknown severity must map to a valid SARIF level, got '{result['level']}'"
    )
