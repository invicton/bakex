# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Parse ARF/XCCDF XML result files into structured Python dicts."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

# XML namespace prefixes used by OpenSCAP ARF output
_NS = {
    "arf": "http://scap.nist.gov/schema/asset-reporting-format/1.1",
    "xccdf": "http://checklists.nist.gov/xccdf/1.2",
    "oval": "http://oval.mitre.org/XMLSchema/oval-results-5",
    "dc": "http://purl.org/dc/elements/1.1/",
}

RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULT_NOT_CHECKED = "notchecked"
RESULT_NOT_APPLICABLE = "notapplicable"
RESULT_ERROR = "error"


def parse_arf(arf_path: Path) -> dict:
    """Parse an ARF XML file and return a summary dict.

    Returns:
        {
            "benchmark_id": str,
            "profile_id": str,
            "start_time": str,
            "end_time": str,
            "score": float | None,
            "rules": [{"id": str, "result": str, "severity": str, "title": str}],
            "counts": {"pass": int, "fail": int, "error": int, "notchecked": int, ...},
        }
    """
    tree = ET.parse(arf_path)
    root = tree.getroot()

    # Locate the TestResult element inside the ARF
    test_result = _find_test_result(root)
    if test_result is None:
        raise ValueError(f"No xccdf:TestResult found in {arf_path}")

    benchmark_el = test_result.find("xccdf:benchmark", _NS)
    profile_el = test_result.find("xccdf:profile", _NS)
    score_el = test_result.find("xccdf:score", _NS)

    rules = _parse_rule_results(test_result)
    counts: dict[str, int] = {}
    for rule in rules:
        counts[rule["result"]] = counts.get(rule["result"], 0) + 1

    return {
        "benchmark_id": benchmark_el.get("id", "") if benchmark_el is not None else "",
        "profile_id": profile_el.get("idref", "") if profile_el is not None else "",
        "start_time": test_result.get("start-time", ""),
        "end_time": test_result.get("end-time", ""),
        "score": float(score_el.text) if score_el is not None and score_el.text else None,
        "rules": rules,
        "counts": counts,
    }


def _find_test_result(root: ET.Element) -> ET.Element | None:
    # ARF wraps XCCDF inside asset-report-collection > reports > report > content
    for content in root.iter("{http://scap.nist.gov/schema/asset-reporting-format/1.1}content"):
        tr = content.find("xccdf:TestResult", _NS)
        if tr is not None:
            return tr
    # Fallback: maybe the root is already XCCDF
    return root.find("xccdf:TestResult", _NS)


def _parse_rule_results(test_result: ET.Element) -> list[dict]:
    rules = []
    for rr in test_result.findall("xccdf:rule-result", _NS):
        result_el = rr.find("xccdf:result", _NS)
        rules.append(
            {
                "id": rr.get("idref", ""),
                "severity": rr.get("severity", "unknown"),
                "result": result_el.text.strip() if result_el is not None and result_el.text else "unknown",
                "title": "",  # Populated from benchmark definition if available
            }
        )
    return rules


def compute_delta(baseline: dict, current: dict) -> dict:
    """Compare two parsed scan results and return a delta report.

    Returns:
        {
            "new_failures": [rule_id, ...],
            "fixed": [rule_id, ...],
            "unchanged_failures": [rule_id, ...],
            "score_delta": float | None,
        }
    """
    baseline_fails = {r["id"] for r in baseline["rules"] if r["result"] == RESULT_FAIL}
    current_fails = {r["id"] for r in current["rules"] if r["result"] == RESULT_FAIL}

    score_delta: float | None = None
    if baseline.get("score") is not None and current.get("score") is not None:
        score_delta = current["score"] - baseline["score"]

    return {
        "new_failures": sorted(current_fails - baseline_fails),
        "fixed": sorted(baseline_fails - current_fails),
        "unchanged_failures": sorted(baseline_fails & current_fails),
        "score_delta": score_delta,
    }
