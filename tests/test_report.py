# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for bakex.core.report — Phase 1 TDD red run.

This file defines the contract for the enriched report module.
Every test that fails is a missing capability, not a pre-existing bug.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bakex.core.report import (
    ReportFormatter,
    format_report,
    generate_delta_report,
    generate_executive_summary,
    generate_summary,
    register_formatter,
)

# ---------------------------------------------------------------------------
# ARF fixture helpers (reuse pattern from test_openscap_parser.py)
# ---------------------------------------------------------------------------

_ARF_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<arf:asset-report-collection
    xmlns:arf="http://scap.nist.gov/schema/asset-reporting-format/1.1">
  <arf:reports>
    <arf:report id="xccdf1">
      <arf:content>
        <xccdf:TestResult
            xmlns:xccdf="http://checklists.nist.gov/xccdf/1.2"
            id="xccdf_result_1"
            start-time="{start}"
            end-time="{end}">
          <xccdf:benchmark id="{benchmark}" />
          <xccdf:profile idref="{profile}" />
          <xccdf:score>{score}</xccdf:score>
          {rule_results}
        </xccdf:TestResult>
      </arf:content>
    </arf:report>
  </arf:reports>
</arf:asset-report-collection>
"""

_RULE_TMPL = (
    '<xccdf:rule-result xmlns:xccdf="http://checklists.nist.gov/xccdf/1.2" '
    'idref="{rule_id}" severity="{severity}"><xccdf:result>{result}</xccdf:result>'
    "</xccdf:rule-result>"
)


def _make_arf(
    tmp_path: Path,
    rules: list[dict],
    score: float = 85.0,
    start: str = "2026-01-01T00:00:00",
    end: str = "2026-01-01T00:05:00",
    name: str = "results",
) -> Path:
    rule_xml = "\n".join(_RULE_TMPL.format(**r) for r in rules)
    xml = _ARF_TEMPLATE.format(
        benchmark="xccdf_test_benchmark",
        profile="xccdf_test_profile_cis_l1",
        score=score,
        start=start,
        end=end,
        rule_results=rule_xml,
    )
    p = tmp_path / f"{name}-arf.xml"
    p.write_text(xml)
    return p


def _rule(rule_id: str, result: str = "fail", severity: str = "high") -> dict:
    return {"rule_id": rule_id, "result": result, "severity": severity}


# ===========================================================================
# generate_summary
# ===========================================================================


class TestGenerateSummary:
    # RS-01: grade A–F present based on score
    def test_grade_present_and_correct(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass", "high")], score=92.0)
        s = generate_summary(arf)
        assert "grade" in s, "generate_summary must include 'grade'"
        assert s["grade"] == "A"

    def test_grade_b_for_score_80(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=80.0)
        assert generate_summary(arf)["grade"] == "B"

    def test_grade_f_for_score_30(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail", "critical")], score=30.0)
        assert generate_summary(arf)["grade"] == "F"

    # RS-02: severity_counts present (failures only)
    def test_severity_counts_present(self, tmp_path):
        arf = _make_arf(
            tmp_path,
            [
                _rule("r1", "fail", "critical"),
                _rule("r2", "fail", "high"),
                _rule("r3", "fail", "medium"),
                _rule("r4", "pass", "low"),
            ],
            score=60.0,
        )
        s = generate_summary(arf)
        assert "severity_counts" in s, "generate_summary must include 'severity_counts'"
        counts = s["severity_counts"]
        assert counts.get("critical") == 1
        assert counts.get("high") == 1
        assert counts.get("medium") == 1
        assert counts.get("low", 0) == 0, "passing rules must not count toward severity_counts"

    # RS-03: top_failures list of highest-severity failures (max 10)
    def test_top_failures_present(self, tmp_path):
        rules = [_rule(f"r{i}", "fail", "high") for i in range(5)]
        arf = _make_arf(tmp_path, rules, score=50.0)
        s = generate_summary(arf)
        assert "top_failures" in s, "generate_summary must include 'top_failures'"
        assert len(s["top_failures"]) == 5

    def test_top_failures_capped_at_ten(self, tmp_path):
        rules = [_rule(f"r{i}", "fail", "medium") for i in range(15)]
        arf = _make_arf(tmp_path, rules, score=40.0)
        s = generate_summary(arf)
        assert len(s["top_failures"]) <= 10, "top_failures must be capped at 10"

    def test_top_failures_sorted_critical_first(self, tmp_path):
        arf = _make_arf(
            tmp_path,
            [
                _rule("low_rule", "fail", "low"),
                _rule("critical_rule", "fail", "critical"),
                _rule("high_rule", "fail", "high"),
            ],
            score=50.0,
        )
        s = generate_summary(arf)
        severities = [f["severity"] for f in s["top_failures"]]
        assert severities[0] == "critical", "critical findings must appear first in top_failures"

    def test_top_failures_only_include_failures(self, tmp_path):
        arf = _make_arf(
            tmp_path,
            [
                _rule("pass_rule", "pass", "high"),
                _rule("fail_rule", "fail", "high"),
            ],
            score=50.0,
        )
        s = generate_summary(arf)
        ids = [f["id"] for f in s["top_failures"]]
        assert "pass_rule" not in ids
        assert "fail_rule" in ids

    # RS-04: risk_score present (0–100)
    def test_risk_score_present(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail", "critical")], score=50.0)
        s = generate_summary(arf)
        assert "risk_score" in s, "generate_summary must include 'risk_score'"
        assert 0 <= s["risk_score"] <= 100

    # RS-05: perfect score → risk_score near 0
    def test_perfect_score_low_risk(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass", "high")], score=100.0)
        assert generate_summary(arf)["risk_score"] == 0.0

    # RS-06: all critical failures → high risk_score
    def test_all_critical_failures_high_risk(self, tmp_path):
        rules = [_rule(f"r{i}", "fail", "critical") for i in range(5)]
        arf = _make_arf(tmp_path, rules, score=0.0)
        assert generate_summary(arf)["risk_score"] == 100.0

    # RS-07: pass_pct correct
    def test_pass_pct_correct(self, tmp_path):
        arf = _make_arf(
            tmp_path,
            [
                _rule("r1", "pass", "high"),
                _rule("r2", "pass", "high"),
                _rule("r3", "fail", "high"),
                _rule("r4", "fail", "high"),
            ],
            score=50.0,
        )
        s = generate_summary(arf)
        assert s["pass_pct"] == pytest.approx(50.0)

    # RS-08: missing file → FileNotFoundError
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            generate_summary(tmp_path / "nonexistent.xml")

    # RS-09: existing fields still present
    def test_existing_fields_intact(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0)
        s = generate_summary(arf)
        for field in ("benchmark_id", "profile_id", "start_time", "end_time", "score", "counts"):
            assert field in s, f"Existing field '{field}' must still be present"


# ===========================================================================
# generate_delta_report
# ===========================================================================


class TestGenerateDeltaReport:
    # RD-01: trend = "improved" when score increases
    def test_trend_improved(self, tmp_path):
        baseline = _make_arf(tmp_path, [_rule("r1", "fail")], score=60.0, name="base")
        current = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0, name="curr")
        delta = generate_delta_report(baseline, current)
        assert "trend" in delta, "generate_delta_report must include 'trend'"
        assert delta["trend"] == "improved"

    # RD-02: trend = "degraded" when score decreases
    def test_trend_degraded(self, tmp_path):
        baseline = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0, name="base")
        current = _make_arf(tmp_path, [_rule("r1", "fail")], score=60.0, name="curr")
        delta = generate_delta_report(baseline, current)
        assert delta["trend"] == "degraded"

    # RD-03: trend = "stable" when score unchanged
    def test_trend_stable(self, tmp_path):
        rules = [_rule("r1", "fail", "medium")]
        baseline = _make_arf(tmp_path, rules, score=75.0, name="base")
        current = _make_arf(tmp_path, rules, score=75.0, name="curr")
        delta = generate_delta_report(baseline, current)
        assert delta["trend"] == "stable"

    # RD-04: regression_count = number of new failures
    def test_regression_count(self, tmp_path):
        baseline = _make_arf(
            tmp_path,
            [
                _rule("r1", "pass"),
                _rule("r2", "pass"),
            ],
            score=100.0,
            name="base",
        )
        current = _make_arf(
            tmp_path,
            [
                _rule("r1", "fail"),
                _rule("r2", "fail"),
            ],
            score=50.0,
            name="curr",
        )
        delta = generate_delta_report(baseline, current)
        assert "regression_count" in delta
        assert delta["regression_count"] == 2

    # RD-05: fixed_count = number of rules fixed
    def test_fixed_count(self, tmp_path):
        baseline = _make_arf(
            tmp_path,
            [
                _rule("r1", "fail"),
                _rule("r2", "fail"),
                _rule("r3", "fail"),
            ],
            score=40.0,
            name="base",
        )
        current = _make_arf(
            tmp_path,
            [
                _rule("r1", "pass"),
                _rule("r2", "pass"),
                _rule("r3", "fail"),
            ],
            score=80.0,
            name="curr",
        )
        delta = generate_delta_report(baseline, current)
        assert "fixed_count" in delta
        assert delta["fixed_count"] == 2

    # RD-06: new_failures_by_severity groups new failures
    def test_new_failures_by_severity(self, tmp_path):
        baseline = _make_arf(
            tmp_path,
            [
                _rule("r1", "pass", "critical"),
                _rule("r2", "pass", "high"),
            ],
            score=100.0,
            name="base",
        )
        current = _make_arf(
            tmp_path,
            [
                _rule("r1", "fail", "critical"),
                _rule("r2", "fail", "high"),
            ],
            score=50.0,
            name="curr",
        )
        delta = generate_delta_report(baseline, current)
        assert "new_failures_by_severity" in delta
        by_sev = delta["new_failures_by_severity"]
        assert "critical" in by_sev
        assert "high" in by_sev

    # RD-07: pct_change is correct
    def test_pct_change_calculated(self, tmp_path):
        baseline = _make_arf(tmp_path, [_rule("r1", "fail")], score=50.0, name="base")
        current = _make_arf(tmp_path, [_rule("r1", "pass")], score=100.0, name="curr")
        delta = generate_delta_report(baseline, current)
        assert "pct_change" in delta
        assert delta["pct_change"] == pytest.approx(100.0)  # doubled

    # RD-08: existing fields still present
    def test_existing_fields_intact(self, tmp_path):
        baseline = _make_arf(tmp_path, [_rule("r1", "fail")], score=60.0, name="base")
        current = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0, name="curr")
        delta = generate_delta_report(baseline, current)
        for field in ("score_before", "score_after", "new_failures", "fixed", "unchanged_failures"):
            assert field in delta, f"Existing field '{field}' must still be present"


# ===========================================================================
# generate_executive_summary
# ===========================================================================


class TestGenerateExecutiveSummary:
    # RE-01: headline is a non-empty string
    def test_headline_present(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=92.0)
        ex = generate_executive_summary(arf)
        assert "headline" in ex, "executive summary must include 'headline'"
        assert isinstance(ex["headline"], str)
        assert len(ex["headline"]) > 0

    # RE-02: headline contains the grade
    def test_headline_contains_grade(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=92.0)
        ex = generate_executive_summary(arf)
        assert "A" in ex["headline"], "headline must contain the letter grade"

    # RE-03: compliance_status is "compliant" or "non-compliant"
    def test_compliance_status_compliant(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0)
        ex = generate_executive_summary(arf)
        assert "compliance_status" in ex
        assert ex["compliance_status"] == "compliant"

    def test_compliance_status_non_compliant(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail", "critical")], score=30.0)
        ex = generate_executive_summary(arf)
        assert ex["compliance_status"] == "non-compliant"

    # RE-04: key_risks — up to 3 critical/high findings
    def test_key_risks_present(self, tmp_path):
        arf = _make_arf(
            tmp_path,
            [
                _rule("crit1", "fail", "critical"),
                _rule("high1", "fail", "high"),
                _rule("med1", "fail", "medium"),
            ],
            score=40.0,
        )
        ex = generate_executive_summary(arf)
        assert "key_risks" in ex
        assert isinstance(ex["key_risks"], list)

    def test_key_risks_capped_at_three(self, tmp_path):
        rules = [_rule(f"crit{i}", "fail", "critical") for i in range(10)]
        arf = _make_arf(tmp_path, rules, score=10.0)
        ex = generate_executive_summary(arf)
        assert len(ex["key_risks"]) <= 3, "key_risks must show at most 3 items"

    def test_key_risks_only_critical_and_high(self, tmp_path):
        arf = _make_arf(
            tmp_path,
            [
                _rule("crit1", "fail", "critical"),
                _rule("med1", "fail", "medium"),
                _rule("low1", "fail", "low"),
            ],
            score=40.0,
        )
        ex = generate_executive_summary(arf)
        for risk in ex["key_risks"]:
            assert risk["severity"] in ("critical", "high"), (
                "key_risks must only include critical or high severity findings"
            )

    # RE-05: action_items list present and non-empty when there are failures
    def test_action_items_present_when_failures(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail", "critical")], score=50.0)
        ex = generate_executive_summary(arf)
        assert "action_items" in ex
        assert len(ex["action_items"]) > 0

    def test_action_items_empty_when_all_pass(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass"), _rule("r2", "pass")], score=100.0)
        ex = generate_executive_summary(arf)
        assert ex["action_items"] == []

    # RE-06: total_findings count
    def test_total_findings_count(self, tmp_path):
        arf = _make_arf(
            tmp_path,
            [
                _rule("r1", "fail"),
                _rule("r2", "fail"),
                _rule("r3", "pass"),
            ],
            score=33.3,
        )
        ex = generate_executive_summary(arf)
        assert "total_findings" in ex
        assert ex["total_findings"] == 2


# ===========================================================================
# format_report — modular formatter system
# ===========================================================================


class TestFormatReport:
    # RF-01: format_report(report, "json") returns valid JSON string
    def test_json_format_is_valid_json(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail")], score=70.0)
        report = generate_summary(arf)
        output = format_report(report, "json")
        assert isinstance(output, str)
        parsed = json.loads(output)  # must not raise
        assert parsed["grade"] == report["grade"]

    # RF-02: format_report(report, "markdown") returns string with # headings
    def test_markdown_format_contains_headings(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail")], score=70.0)
        report = generate_summary(arf)
        output = format_report(report, "markdown")
        assert isinstance(output, str)
        assert "#" in output, "Markdown output must contain at least one heading"

    # RF-03: format_report(report, "text") returns plain text
    def test_text_format_returns_string(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail")], score=70.0)
        report = generate_summary(arf)
        output = format_report(report, "text")
        assert isinstance(output, str)
        assert len(output) > 0

    # RF-04: unknown format raises ValueError
    def test_unknown_format_raises_value_error(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0)
        report = generate_summary(arf)
        with pytest.raises(ValueError, match="Unknown report format"):
            format_report(report, "docx")

    # RF-05: register_formatter adds custom formatter
    def test_register_custom_formatter(self, tmp_path):
        class CsvFormatter(ReportFormatter):
            def format(self, report: dict) -> str:
                return f"grade,score\n{report.get('grade')},{report.get('score')}"

        register_formatter("csv", CsvFormatter)

        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0)
        report = generate_summary(arf)
        output = format_report(report, "csv")
        assert "grade,score" in output

    # RF-06: custom formatter is callable via format_report after registration
    def test_custom_formatter_invoked(self, tmp_path):
        called = []

        class TrackFormatter(ReportFormatter):
            def format(self, report: dict) -> str:
                called.append(True)
                return "tracked"

        register_formatter("track", TrackFormatter)

        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=90.0)
        report = generate_summary(arf)
        result = format_report(report, "track")
        assert called, "Custom formatter must be called"
        assert result == "tracked"

    # RF-07: Markdown output contains grade and score
    def test_markdown_contains_grade_and_score(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "pass")], score=92.0)
        report = generate_summary(arf)
        output = format_report(report, "markdown")
        assert "A" in output, "Markdown must contain the grade"
        assert "92" in output, "Markdown must contain the score"

    # RF-08: Text format contains grade
    def test_text_format_contains_grade(self, tmp_path):
        arf = _make_arf(tmp_path, [_rule("r1", "fail", "high")], score=65.0)
        report = generate_summary(arf)
        output = format_report(report, "text")
        assert "C" in output, "Text output must contain the grade"
