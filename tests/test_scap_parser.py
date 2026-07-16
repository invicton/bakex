# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Unit tests for SCAPParser and Exception Engine."""

from __future__ import annotations

import pytest

from statim.core.parser import SCAPParser

_XCCDF_NS = "http://checklists.nist.gov/xccdf/1.2"

# --- Helpers -------------------------------------------------------------------


def _make_xml(rules: list[tuple[str, str]], score: float | None = 87.5) -> str:
    """Build a minimal XCCDF TestResult XML string."""
    score_el = f"<xccdf:score>{score}</xccdf:score>" if score is not None else ""
    rule_els = ""
    for rule_id, result in rules:
        rule_els += f"""
        <xccdf:rule-result idref="{rule_id}" severity="medium">
          <xccdf:result>{result}</xccdf:result>
        </xccdf:rule-result>"""
    return f"""<?xml version="1.0"?>
<xccdf:TestResult xmlns:xccdf="{_XCCDF_NS}" id="result_1">
  {score_el}
  {rule_els}
</xccdf:TestResult>"""


# --- TestSCAPParser ------------------------------------------------------------


class TestSCAPParser:
    def test_basic_pass_fail(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_accounts_min_age", "pass"),
                ("xccdf_org.ssgproject.content_rule_accounts_max_age", "fail"),
            ],
            score=75.0,
        )
        result = SCAPParser.parse_report(xml, blueprint={})
        assert result["score"] == 75.0
        assert result["total_rules"] == 2
        assert result["passed"] == 1
        assert result["failed"] == 1
        assert result["approved_exceptions"] == 0

    def test_all_pass(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_r1", "pass"),
                ("xccdf_org.ssgproject.content_rule_r2", "pass"),
                ("xccdf_org.ssgproject.content_rule_r3", "pass"),
            ],
            score=100.0,
        )
        result = SCAPParser.parse_report(xml, blueprint={})
        assert result["passed"] == 3
        assert result["failed"] == 0
        assert result["score"] == 100.0

    def test_score_none_when_missing(self):
        xml = _make_xml([("xccdf_org.ssgproject.content_rule_r1", "pass")], score=None)
        result = SCAPParser.parse_report(xml, blueprint={})
        assert result["score"] is None

    def test_findings_have_rule_ids(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_accounts_min_age", "pass"),
            ]
        )
        result = SCAPParser.parse_report(xml, blueprint={})
        assert result["findings"][0]["rule_id"] == "accounts_min_age"


# --- TestExceptionEngine -------------------------------------------------------


class TestExceptionEngine:
    def test_fail_with_override_becomes_approved_exception(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_accounts_max_age", "fail"),
            ]
        )
        blueprint = {"controls": {"accounts_max_age": {"enabled": False, "justification": "Legacy system waiver"}}}
        result = SCAPParser.parse_report(xml, blueprint=blueprint)
        assert result["approved_exceptions"] == 1
        assert result["failed"] == 0
        assert result["findings"][0]["status"] == "approved_exception"

    def test_fail_without_override_stays_fail(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_accounts_max_age", "fail"),
            ]
        )
        blueprint = {"controls": {}}
        result = SCAPParser.parse_report(xml, blueprint=blueprint)
        assert result["failed"] == 1
        assert result["approved_exceptions"] == 0
        assert result["findings"][0]["status"] == "fail"

    def test_bool_false_override_is_approved_exception(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_some_rule", "fail"),
            ]
        )
        blueprint = {"controls": {"some_rule": False}}
        result = SCAPParser.parse_report(xml, blueprint=blueprint)
        assert result["approved_exceptions"] == 1

    def test_bool_true_override_does_not_excuse_fail(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_some_rule", "fail"),
            ]
        )
        blueprint = {"controls": {"some_rule": True}}
        result = SCAPParser.parse_report(xml, blueprint=blueprint)
        assert result["failed"] == 1
        assert result["approved_exceptions"] == 0

    def test_enabled_override_does_not_affect_pass(self):
        xml = _make_xml(
            [
                ("xccdf_org.ssgproject.content_rule_some_rule", "pass"),
            ]
        )
        blueprint = {"controls": {"some_rule": {"enabled": False, "justification": "Waived"}}}
        result = SCAPParser.parse_report(xml, blueprint=blueprint)
        # pass stays pass regardless of override
        assert result["passed"] == 1
        assert result["approved_exceptions"] == 0


# --- TestMapRuleId ------------------------------------------------------------


class TestMapRuleId:
    def test_extracts_rule_suffix(self):
        full_id = "xccdf_org.ssgproject.content_rule_accounts_password_minlen_login_defs"
        assert SCAPParser._map_rule_id(full_id) == "accounts_password_minlen_login_defs"

    def test_no_rule_marker_returns_last_segment(self):
        assert SCAPParser._map_rule_id("some_id_here") == "here"

    def test_plain_id_unchanged(self):
        assert SCAPParser._map_rule_id("simple") == "simple"


# --- TestMissingTestResult ----------------------------------------------------


class TestMissingTestResult:
    def test_invalid_xml_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid XCCDF XML"):
            SCAPParser.parse_report("not xml at all <<<", blueprint={})

    def test_xml_without_test_result_raises_value_error(self):
        xml = '<?xml version="1.0"?><root><child/></root>'
        with pytest.raises(ValueError, match="No xccdf:TestResult"):
            SCAPParser.parse_report(xml, blueprint={})
