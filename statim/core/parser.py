# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""SCAPParser — parse cloud XCCDF XML output with Exception Engine.

Distinct from statim/openscap/parser.py which handles local ARF files.
This parser processes raw XCCDF XML returned by SSM (cloud audit path)
and applies the blueprint's ControlOverride exception logic.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


class SCAPParser:
    XCCDF_NS = {"xccdf": "http://checklists.nist.gov/xccdf/1.2"}

    @classmethod
    def parse_report(cls, xml_string: str, blueprint: dict) -> dict:
        """Parse XCCDF XML and apply exception engine against the blueprint.

        Args:
            xml_string: Raw XCCDF XML string returned by the cloud audit.
            blueprint: ``profile.model_dump()`` — used by the exception engine.

        Returns:
            {
                "score": float | None,
                "total_rules": int,
                "passed": int,
                "failed": int,
                "approved_exceptions": int,
                "findings": [
                    {
                        "rule_id": str,
                        "status": "pass" | "fail" | "approved_exception",
                        "severity": str,
                    },
                    ...
                ],
            }
        """
        try:
            root = ET.fromstring(xml_string)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid XCCDF XML: {exc}") from exc

        test_result = cls._find_test_result(root)
        if test_result is None:
            raise ValueError("No xccdf:TestResult element found in XML")

        score_el = test_result.find("xccdf:score", cls.XCCDF_NS)
        score: float | None = None
        if score_el is not None and score_el.text:
            try:
                score = float(score_el.text.strip())
            except ValueError:
                pass

        controls: dict = blueprint.get("controls", {})
        findings = []
        passed = 0
        failed = 0
        approved_exceptions = 0

        for rr in test_result.findall("xccdf:rule-result", cls.XCCDF_NS):
            scap_id = rr.get("idref", "")
            severity = rr.get("severity", "unknown")
            result_el = rr.find("xccdf:result", cls.XCCDF_NS)
            raw_result = result_el.text.strip() if result_el is not None and result_el.text else "unknown"

            friendly_id = cls._map_rule_id(scap_id)

            if raw_result == "pass":
                status = "pass"
                passed += 1
            elif raw_result == "fail":
                # Check exception engine — use explicit key presence check to handle False values
                _sentinel = object()
                _override = controls.get(friendly_id, _sentinel)
                override = _override if _override is not _sentinel else controls.get(scap_id)
                if cls._is_approved_exception(override):
                    status = "approved_exception"
                    approved_exceptions += 1
                else:
                    status = "fail"
                    failed += 1
            else:
                # notchecked, notapplicable, error, etc. — count as pass equivalent
                status = raw_result
                passed += 1

            findings.append(
                {
                    "rule_id": friendly_id,
                    "scap_id": scap_id,
                    "status": status,
                    "severity": severity,
                }
            )

        total_rules = passed + failed + approved_exceptions

        return {
            "score": score,
            "total_rules": total_rules,
            "passed": passed,
            "failed": failed,
            "approved_exceptions": approved_exceptions,
            "findings": findings,
        }

    @classmethod
    def _find_test_result(cls, root: ET.Element) -> ET.Element | None:
        # Direct child
        tr = root.find("xccdf:TestResult", cls.XCCDF_NS)
        if tr is not None:
            return tr
        # Nested (ARF wrapper)
        for el in root.iter("{http://checklists.nist.gov/xccdf/1.2}TestResult"):
            return el
        return None

    @staticmethod
    def _map_rule_id(scap_id: str) -> str:
        """Extract a short friendly rule ID from a full SCAP URI.

        Examples:
            xccdf_org.ssgproject.content_rule_accounts_password_minlen_login_defs
            → accounts_password_minlen_login_defs
        """
        if "_rule_" in scap_id:
            return scap_id.split("_rule_", 1)[-1]
        # Fallback: last segment after the last underscore group
        parts = scap_id.rsplit("_", 1)
        return parts[-1] if len(parts) > 1 else scap_id

    @staticmethod
    def _is_approved_exception(override) -> bool:
        """Return True if the override marks the control as disabled with justification."""
        if override is None:
            return False
        # bool shorthand (True = enabled, False = disabled without justification)
        if isinstance(override, bool):
            return not override
        # dict representation of ControlOverride
        if isinstance(override, dict):
            return not override.get("enabled", True)
        # Pydantic model
        return not getattr(override, "enabled", True)
