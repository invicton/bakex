# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for pipeline pass/fail threshold logic — Phase 1 TDD red run.

Tests the _job_to_response helper and score_to_grade directly, without
starting a server or touching any cloud resources.
"""

from __future__ import annotations

from statim.api.pipeline import _job_to_response
from statim.core.auditor import AuditJob, AuditStatus, score_to_grade

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    score_pct: float | None = None,
    severity_counts: dict | None = None,
    status: AuditStatus = AuditStatus.COMPLETE,
    grade: str | None = None,
) -> AuditJob:
    job = AuditJob(
        job_type="image_scan",
        image_id="ami-test",
        provider="aws",
        region="us-east-1",
        profile_name="test-profile",
        target_host="ami-test",
        status=status,
    )
    job.score_pct = score_pct
    job.severity_counts = severity_counts or {}
    job.grade = grade or (score_to_grade(score_pct) if score_pct is not None else None)
    return job


# ---------------------------------------------------------------------------
# score_to_grade boundary tests
# ---------------------------------------------------------------------------


class TestScoreToGrade:
    def test_score_90_is_A(self):
        assert score_to_grade(90.0) == "A"

    def test_score_100_is_A(self):
        assert score_to_grade(100.0) == "A"

    def test_score_89_9_is_B(self):
        assert score_to_grade(89.9) == "B"

    def test_score_75_is_B(self):
        assert score_to_grade(75.0) == "B"

    def test_score_74_9_is_C(self):
        assert score_to_grade(74.9) == "C"

    def test_score_60_is_C(self):
        assert score_to_grade(60.0) == "C"

    def test_score_59_9_is_D(self):
        assert score_to_grade(59.9) == "D"

    def test_score_40_is_D(self):
        assert score_to_grade(40.0) == "D"

    def test_score_39_9_is_F(self):
        assert score_to_grade(39.9) == "F"

    def test_score_0_is_F(self):
        assert score_to_grade(0.0) == "F"


# ---------------------------------------------------------------------------
# PL-01: score above threshold → passed
# ---------------------------------------------------------------------------


def test_score_above_threshold_passes():
    job = _make_job(score_pct=80.0)
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# PL-02: score below threshold → failed
# ---------------------------------------------------------------------------


def test_score_below_threshold_fails():
    job = _make_job(score_pct=60.0)
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# PL-03: high severity finding fails even at 100% score
# ---------------------------------------------------------------------------


def test_high_severity_fails_despite_perfect_score():
    job = _make_job(score_pct=100.0, severity_counts={"high": 1, "critical": 0, "medium": 0, "low": 0})
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    assert result["passed"] is False, "High severity finding must cause failure regardless of score"


# ---------------------------------------------------------------------------
# PL-04: medium finding below high threshold → passed (if score ok)
# ---------------------------------------------------------------------------


def test_medium_finding_below_high_threshold_passes():
    job = _make_job(score_pct=80.0, severity_counts={"high": 0, "critical": 0, "medium": 5, "low": 3})
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    assert result["passed"] is True, "Medium findings should not fail when threshold is 'high'"


# ---------------------------------------------------------------------------
# PL-05: threshold_violations lists exact failing severities
# ---------------------------------------------------------------------------


def test_threshold_violations_lists_correct_severities():
    job = _make_job(
        score_pct=95.0,
        severity_counts={"critical": 2, "high": 1, "medium": 0, "low": 0},
    )
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    violations = result["threshold_violations"]
    assert "critical" in violations, "critical must appear in threshold_violations"
    assert "high" in violations, "high must appear in threshold_violations"
    assert "medium" not in violations
    assert "low" not in violations


# ---------------------------------------------------------------------------
# PL-06: default thresholds reflected in response
# ---------------------------------------------------------------------------


def test_response_contains_threshold_values():
    job = _make_job(score_pct=80.0)
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    assert result["pass_threshold"] == 75.0
    assert result["severity_threshold"] == "high"


# ---------------------------------------------------------------------------
# Extra: score exactly at threshold boundary → passed
# ---------------------------------------------------------------------------


def test_score_exactly_at_threshold_passes():
    job = _make_job(score_pct=75.0)
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    assert result["passed"] is True, "Score exactly equal to threshold must pass"


# ---------------------------------------------------------------------------
# Extra: critical finding at threshold=high fails; same at threshold=critical also fails
# ---------------------------------------------------------------------------


def test_critical_finding_fails_at_critical_threshold():
    job = _make_job(score_pct=95.0, severity_counts={"critical": 1, "high": 0, "medium": 0, "low": 0})
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="critical")
    assert result["passed"] is False


def test_medium_finding_fails_at_medium_threshold():
    job = _make_job(score_pct=95.0, severity_counts={"critical": 0, "high": 0, "medium": 3, "low": 0})
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="medium")
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# Extra: response contains all required keys for CI integration
# ---------------------------------------------------------------------------


def test_response_contains_all_ci_keys():
    job = _make_job(score_pct=80.0)
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    required = {
        "job_id",
        "status",
        "passed",
        "grade",
        "score_pct",
        "severity_counts",
        "threshold_violations",
        "pass_threshold",
        "severity_threshold",
        "image_id",
        "provider",
        "region",
        "profile",
        "error",
        "report_url",
        "sarif_url",
        "html_report_url",
    }
    missing = required - result.keys()
    assert not missing, f"Response missing required keys: {missing}"


# ---------------------------------------------------------------------------
# Extra: score None → passed is False (no score = cannot pass gate)
# ---------------------------------------------------------------------------


def test_null_score_does_not_pass():
    job = _make_job(score_pct=None)
    result = _job_to_response(job, pass_threshold=75.0, severity_threshold="high")
    assert result["passed"] is False, "A job with no score must not pass the pipeline gate"
