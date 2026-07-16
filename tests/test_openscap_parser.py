# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for ARF/XCCDF XML parsing and delta computation."""

from __future__ import annotations

from pathlib import Path

import pytest

from statim.openscap.parser import (
    compute_delta,
    parse_arf,
)

# Minimal valid ARF XML fixture
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

_RULE_TMPL = """\
<xccdf:rule-result
    xmlns:xccdf="http://checklists.nist.gov/xccdf/1.2"
    idref="{rule_id}" severity="{severity}">
  <xccdf:result>{result}</xccdf:result>
</xccdf:rule-result>"""


def _make_arf(tmp_path, rules: list[dict], score=85.0, start="2024-01-01T00:00:00", end="2024-01-01T00:01:00") -> Path:
    rule_xml = "\n".join(_RULE_TMPL.format(**r) for r in rules)
    xml = _ARF_TEMPLATE.format(
        benchmark="xccdf_test_benchmark",
        profile="xccdf_test_profile",
        score=score,
        start=start,
        end=end,
        rule_results=rule_xml,
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "results-arf.xml"
    p.write_text(xml)
    return p


def test_parse_arf_basic(tmp_path):
    arf = _make_arf(
        tmp_path,
        [
            {"rule_id": "rule_001", "severity": "high", "result": "pass"},
            {"rule_id": "rule_002", "severity": "medium", "result": "fail"},
        ],
    )
    result = parse_arf(arf)
    assert result["benchmark_id"] == "xccdf_test_benchmark"
    assert result["score"] == 85.0
    assert len(result["rules"]) == 2


def test_parse_arf_counts(tmp_path):
    arf = _make_arf(
        tmp_path,
        [
            {"rule_id": "r1", "severity": "high", "result": "pass"},
            {"rule_id": "r2", "severity": "high", "result": "pass"},
            {"rule_id": "r3", "severity": "medium", "result": "fail"},
        ],
    )
    result = parse_arf(arf)
    assert result["counts"].get("pass") == 2
    assert result["counts"].get("fail") == 1


def test_parse_arf_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_arf(Path("/nonexistent/results.xml"))


def test_compute_delta_new_failure(tmp_path):
    baseline = parse_arf(
        _make_arf(
            tmp_path / "b",
            [
                {"rule_id": "r1", "severity": "high", "result": "pass"},
            ],
            score=100.0,
        )
    )
    current = parse_arf(
        _make_arf(
            tmp_path / "c",
            [
                {"rule_id": "r1", "severity": "high", "result": "fail"},
            ],
            score=70.0,
        )
    )

    delta = compute_delta(baseline, current)
    assert "r1" in delta["new_failures"]
    assert delta["fixed"] == []
    assert delta["score_delta"] == pytest.approx(-30.0)


def test_compute_delta_fixed(tmp_path):
    baseline = parse_arf(
        _make_arf(
            tmp_path / "b",
            [
                {"rule_id": "r1", "severity": "high", "result": "fail"},
            ],
            score=60.0,
        )
    )
    current = parse_arf(
        _make_arf(
            tmp_path / "c",
            [
                {"rule_id": "r1", "severity": "high", "result": "pass"},
            ],
            score=100.0,
        )
    )

    delta = compute_delta(baseline, current)
    assert "r1" in delta["fixed"]
    assert delta["new_failures"] == []
    assert delta["score_delta"] == pytest.approx(40.0)


def test_compute_delta_unchanged(tmp_path):
    rules = [{"rule_id": "r1", "severity": "medium", "result": "fail"}]
    baseline = parse_arf(_make_arf(tmp_path / "b", rules, score=50.0))
    current = parse_arf(_make_arf(tmp_path / "c", rules, score=50.0))

    delta = compute_delta(baseline, current)
    assert "r1" in delta["unchanged_failures"]
    assert delta["new_failures"] == []
    assert delta["fixed"] == []
    assert delta["score_delta"] == pytest.approx(0.0)
