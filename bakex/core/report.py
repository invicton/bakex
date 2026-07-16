# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Compliance report generation — enriched summaries, delta reports, executive views,
and a plug-and-play formatter registry for infra managers and auditors.

Design goals:
  - generate_summary()          : machine-readable enriched dict for any consumer
  - generate_delta_report()     : trend analysis between two scan ARFs
  - generate_executive_summary(): non-technical one-page view for managers / auditors
  - format_report()             : dispatch to pluggable formatters (json, markdown, text)
  - register_formatter()        : drop in a new output format without touching core

All formatters implement ReportFormatter.format(report: dict) -> str.
Register a custom formatter once at startup and it is available globally.
"""

from __future__ import annotations

import abc
import json
from pathlib import Path

from bakex.openscap.parser import RESULT_FAIL, RESULT_PASS, compute_delta, parse_arf

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GRADE_THRESHOLDS = [
    (90.0, "A"),
    (75.0, "B"),
    (60.0, "C"),
    (40.0, "D"),
]

_SEVERITY_ORDER = ["critical", "high", "medium", "low"]

_SEVERITY_WEIGHT = {"critical": 10, "high": 5, "medium": 2, "low": 1}


def _score_to_grade(score: float | None) -> str:
    if score is None:
        return "F"
    for threshold, grade in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _severity_counts_from_rules(rules: list[dict]) -> dict:
    """Count failed rules by severity. Passing rules are excluded."""
    counts: dict[str, int] = {s: 0 for s in _SEVERITY_ORDER}
    for rule in rules:
        if rule.get("result") == RESULT_FAIL:
            sev = rule.get("severity", "low").lower()
            if sev in counts:
                counts[sev] += 1
    return counts


def _risk_score(score: float | None) -> float:
    """Convert compliance score to a 0–100 risk score (complement)."""
    if score is None:
        return 100.0
    return round(max(0.0, min(100.0, 100.0 - score)), 1)


def _top_failures(rules: list[dict], limit: int = 10) -> list[dict]:
    """Return up to *limit* failed rules sorted by severity (critical first)."""
    failed = [r for r in rules if r.get("result") == RESULT_FAIL]
    failed.sort(
        key=lambda r: (
            _SEVERITY_ORDER.index(r.get("severity", "low").lower())
            if r.get("severity", "low").lower() in _SEVERITY_ORDER
            else len(_SEVERITY_ORDER)
        )
    )
    return [
        {"id": r["id"], "severity": r.get("severity", "unknown"), "title": r.get("title", "")} for r in failed[:limit]
    ]


# ---------------------------------------------------------------------------
# Public API — core report functions
# ---------------------------------------------------------------------------


def generate_summary(arf_path: Path) -> dict:
    """Return an enriched summary dict from an ARF file.

    Adds on top of the raw parse result:
      - grade           : letter grade A–F
      - risk_score      : 0–100 (complement of compliance score)
      - severity_counts : {critical, high, medium, low} — failures only
      - top_failures    : up to 10 failed rules, critical-first
      - pass_pct        : percentage of rules that passed

    Args:
        arf_path: Path to an OpenSCAP ARF XML result file.

    Returns:
        Enriched report dict.

    Raises:
        FileNotFoundError: if arf_path does not exist.
    """
    raw = parse_arf(arf_path)
    counts = raw.get("counts", {})
    total = sum(counts.values()) or 1
    passed = counts.get(RESULT_PASS, 0)
    score = raw.get("score")

    return {
        # Existing fields — preserved for backwards compatibility
        "benchmark_id": raw["benchmark_id"],
        "profile_id": raw["profile_id"],
        "start_time": raw["start_time"],
        "end_time": raw["end_time"],
        "score": score,
        "counts": counts,
        # Enriched fields
        "grade": _score_to_grade(score),
        "risk_score": _risk_score(score),
        "pass_pct": round(passed / total * 100, 1),
        "severity_counts": _severity_counts_from_rules(raw.get("rules", [])),
        "top_failures": _top_failures(raw.get("rules", [])),
        "failed_rules": [r for r in raw.get("rules", []) if r["result"] == RESULT_FAIL],
    }


def generate_delta_report(baseline_arf: Path, current_arf: Path) -> dict:
    """Compare two ARF files and return a structured delta report.

    Adds on top of the raw delta:
      - trend                  : "improved" | "degraded" | "stable"
      - regression_count       : number of new failures introduced
      - fixed_count            : number of failures resolved
      - pct_change             : percentage change in score (positive = improvement)
      - new_failures_by_severity: new failures grouped by severity level

    Args:
        baseline_arf: Path to the earlier ARF result (the reference).
        current_arf:  Path to the later ARF result (under evaluation).

    Returns:
        Structured delta dict.
    """
    baseline = parse_arf(baseline_arf)
    current = parse_arf(current_arf)
    delta = compute_delta(baseline, current)

    score_before = baseline.get("score")
    score_after = current.get("score")

    # Trend
    if score_before is None or score_after is None:
        trend = "stable"
    elif score_after > score_before:
        trend = "improved"
    elif score_after < score_before:
        trend = "degraded"
    else:
        trend = "stable"

    # Percentage change (relative to baseline, guarded against div-by-zero)
    if score_before and score_before != 0:
        pct_change = round((score_after - score_before) / score_before * 100, 1)
    else:
        pct_change = 0.0

    # Group new failures by severity using the current scan's rule data
    current_rule_map = {r["id"]: r for r in current.get("rules", [])}
    new_failures_by_severity: dict[str, list[str]] = {s: [] for s in _SEVERITY_ORDER}
    for rule_id in delta.get("new_failures", []):
        rule = current_rule_map.get(rule_id, {})
        sev = rule.get("severity", "low").lower()
        bucket = sev if sev in new_failures_by_severity else "low"
        new_failures_by_severity[bucket].append(rule_id)
    # Remove empty buckets for a clean output
    new_failures_by_severity = {k: v for k, v in new_failures_by_severity.items() if v}

    return {
        # Existing fields — preserved for backwards compatibility
        "baseline_time": baseline.get("start_time"),
        "current_time": current.get("start_time"),
        "score_before": score_before,
        "score_after": score_after,
        "new_failures": delta["new_failures"],
        "fixed": delta["fixed"],
        "unchanged_failures": delta["unchanged_failures"],
        "score_delta": delta.get("score_delta"),
        # Enriched fields
        "trend": trend,
        "regression_count": len(delta["new_failures"]),
        "fixed_count": len(delta["fixed"]),
        "pct_change": pct_change,
        "new_failures_by_severity": new_failures_by_severity,
    }


def generate_executive_summary(arf_path: Path) -> dict:
    """Generate a non-technical one-page executive view for managers and auditors.

    Designed for a dashboard widget or a one-page PDF cover sheet. Contains:
      - headline           : single-line status string (grade + score + key risk count)
      - compliance_status  : "compliant" | "non-compliant" (compliant = grade A or B)
      - grade              : letter grade A–F
      - score              : raw compliance score
      - key_risks          : up to 3 critical/high findings that need immediate action
      - action_items       : bullet-point strings describing what to fix
      - total_findings     : total number of failed rules

    Args:
        arf_path: Path to an OpenSCAP ARF XML result file.

    Returns:
        Executive summary dict.
    """
    summary = generate_summary(arf_path)
    grade = summary["grade"]
    score = summary["score"]
    sev_counts = summary["severity_counts"]
    top = summary["top_failures"]

    # Key risks: only critical and high, max 3
    key_risks = [f for f in top if f["severity"] in ("critical", "high")][:3]

    # Compliance status: A or B = compliant, anything below = non-compliant
    compliance_status = "compliant" if grade in ("A", "B") else "non-compliant"

    # Headline
    high_count = sev_counts.get("critical", 0) + sev_counts.get("high", 0)
    score_str = f"{score:.1f}%" if score is not None else "N/A"
    if high_count > 0:
        headline = (
            f"{grade} — {score_str} compliant ({high_count} critical/high finding{'s' if high_count != 1 else ''})"
        )
    else:
        headline = f"{grade} — {score_str} compliant"

    # Action items: concise strings for remediation
    action_items: list[str] = []
    if sev_counts.get("critical", 0) > 0:
        action_items.append(
            f"Resolve {sev_counts['critical']} critical finding{'s' if sev_counts['critical'] != 1 else ''} immediately"
        )
    if sev_counts.get("high", 0) > 0:
        action_items.append(
            f"Address {sev_counts['high']} high severity finding{'s' if sev_counts['high'] != 1 else ''} before next release"
        )
    if sev_counts.get("medium", 0) > 0:
        action_items.append(
            f"Schedule remediation for {sev_counts['medium']} medium severity finding{'s' if sev_counts['medium'] != 1 else ''}"
        )

    total_findings = sum(1 for r in (summary.get("failed_rules") or []))

    return {
        "headline": headline,
        "compliance_status": compliance_status,
        "grade": grade,
        "score": score,
        "key_risks": key_risks,
        "action_items": action_items,
        "total_findings": total_findings,
        "severity_counts": sev_counts,
    }


# ---------------------------------------------------------------------------
# Pluggable formatter system
# ---------------------------------------------------------------------------


class ReportFormatter(abc.ABC):
    """Base class for all report formatters.

    Subclass this and implement ``format(report)`` to add a new output format.
    Register the subclass via ``register_formatter(name, cls)``.
    """

    @abc.abstractmethod
    def format(self, report: dict) -> str:
        """Serialize *report* to a string in this formatter's target format."""


class _JsonFormatter(ReportFormatter):
    def format(self, report: dict) -> str:
        return json.dumps(report, indent=2, default=str)


class _MarkdownFormatter(ReportFormatter):
    def format(self, report: dict) -> str:
        grade = report.get("grade", "?")
        score = report.get("score")
        score_str = f"{score:.1f}" if score is not None else "N/A"
        risk = report.get("risk_score", "N/A")
        pass_pct = report.get("pass_pct", "N/A")
        sev = report.get("severity_counts", {})

        lines = [
            f"# Compliance Report — Grade {grade}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Score | {score_str}% |",
            f"| Grade | {grade} |",
            f"| Risk Score | {risk} |",
            f"| Pass Rate | {pass_pct}% |",
            "",
            "## Severity Breakdown",
            "",
            "| Severity | Failures |",
            "|----------|---------|",
        ]
        for sev_level in _SEVERITY_ORDER:
            lines.append(f"| {sev_level.capitalize()} | {sev.get(sev_level, 0)} |")

        top = report.get("top_failures", [])
        if top:
            lines += ["", "## Top Findings", ""]
            for i, f in enumerate(top, 1):
                lines.append(f"{i}. **{f['id']}** ({f['severity']})" + (f" — {f['title']}" if f.get("title") else ""))

        return "\n".join(lines)


class _TextFormatter(ReportFormatter):
    def format(self, report: dict) -> str:
        grade = report.get("grade", "?")
        score = report.get("score")
        score_str = f"{score:.1f}%" if score is not None else "N/A"
        sev = report.get("severity_counts", {})

        lines = [
            f"Compliance Report — Grade {grade}",
            f"{'=' * 40}",
            f"Score      : {score_str}",
            f"Risk Score : {report.get('risk_score', 'N/A')}",
            f"Pass Rate  : {report.get('pass_pct', 'N/A')}%",
            "",
            "Severity Breakdown (failures only):",
        ]
        for sev_level in _SEVERITY_ORDER:
            lines.append(f"  {sev_level.capitalize():<10}: {sev.get(sev_level, 0)}")

        top = report.get("top_failures", [])
        if top:
            lines += ["", "Top Findings:"]
            for f in top:
                lines.append(f"  [{f['severity'].upper()}] {f['id']}")

        return "\n".join(lines)


# Registry: name → formatter class
_FORMATTERS: dict[str, type[ReportFormatter]] = {
    "json": _JsonFormatter,
    "markdown": _MarkdownFormatter,
    "text": _TextFormatter,
}


def register_formatter(name: str, cls: type[ReportFormatter]) -> None:
    """Register a custom report formatter under *name*.

    Once registered, ``format_report(report, name)`` will use this class.
    This is the plug-and-play extension point — no core changes required.

    Args:
        name: The format identifier (e.g. "csv", "html", "pdf-json").
        cls:  A subclass of ``ReportFormatter`` that implements ``format()``.

    Example::

        class MyFormatter(ReportFormatter):
            def format(self, report: dict) -> str:
                return ",".join(str(v) for v in report.values())

        register_formatter("csv", MyFormatter)
        output = format_report(my_report, "csv")
    """
    if not (isinstance(cls, type) and issubclass(cls, ReportFormatter)):
        raise TypeError(f"{cls!r} must be a subclass of ReportFormatter")
    _FORMATTERS[name] = cls


def format_report(report: dict, fmt: str = "json") -> str:
    """Serialize *report* using the named formatter.

    Args:
        report: A report dict produced by ``generate_summary`` or similar.
        fmt:    Format name — "json", "markdown", "text", or any registered custom name.

    Returns:
        Formatted string.

    Raises:
        ValueError: if *fmt* is not a known or registered format.
    """
    if fmt not in _FORMATTERS:
        raise ValueError(
            f"Unknown report format '{fmt}'. "
            f"Available: {sorted(_FORMATTERS)}. "
            f"Register new formats with register_formatter()."
        )
    return _FORMATTERS[fmt]().format(report)
