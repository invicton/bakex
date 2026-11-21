# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for compiling blueprint `controls` into an XCCDF tailoring file (#60).

The regression these guard against is subtle: before this, `controls` was inert. A
blueprint could waive a rule, the scan would evaluate it anyway, and the waiver would
cost the author grade points with no error to explain why.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from bakex.core.blueprint import ComplianceProfile
from bakex.openscap.scanner import _build_command
from bakex.openscap.tailoring import (
    TAILORED_PROFILE_ID,
    XCCDF_NS,
    build_tailoring_xml,
    write_tailoring,
)

_RULE_SELINUX = "xccdf_org.ssgproject.content_rule_grub2_enable_selinux"
_RULE_TELNET = "xccdf_org.ssgproject.content_rule_package_telnet_removed"
_BASE_PROFILE = "xccdf_org.ssgproject.content_profile_cis_level1_server"


def _profile(controls: dict | None = None) -> ComplianceProfile:
    return ComplianceProfile.model_validate(
        {
            "bakex_version": "0.6.0",
            "kind": "HardeningBlueprint",
            "metadata": {"name": "test-bp", "version": "1.0.0"},
            "target": {"os": "ubuntu22.04", "provider": "aws", "base_image": "ami-123"},
            "compliance": {
                "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
                "profile": _BASE_PROFILE,
                "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            },
            "controls": controls or {},
        }
    )


def _selects(xml: str) -> dict[str, str]:
    root = ET.fromstring(xml)
    prof = root.find(f"{{{XCCDF_NS}}}Profile")
    return {s.get("idref"): s.get("selected") for s in prof.findall(f"{{{XCCDF_NS}}}select")}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def test_no_controls_produces_no_tailoring():
    """The common path must stay identical to an untailored scan."""
    assert build_tailoring_xml(_profile()) is None


def test_disabled_rule_is_deselected():
    xml = build_tailoring_xml(_profile({_RULE_SELINUX: {"enabled": False, "justification": "AppArmor, not SELinux."}}))
    assert _selects(xml)[_RULE_SELINUX] == "false"


def test_bare_true_is_selected():
    xml = build_tailoring_xml(_profile({_RULE_TELNET: True}))
    assert _selects(xml)[_RULE_TELNET] == "true"


def test_bare_false_is_deselected():
    xml = build_tailoring_xml(_profile({_RULE_TELNET: False}))
    assert _selects(xml)[_RULE_TELNET] == "false"


def test_mixed_controls_round_trip():
    xml = build_tailoring_xml(
        _profile(
            {
                _RULE_SELINUX: {"enabled": False, "justification": "Not applicable."},
                _RULE_TELNET: True,
            }
        )
    )
    assert _selects(xml) == {_RULE_SELINUX: "false", _RULE_TELNET: "true"}


def test_profile_extends_the_blueprints_profile():
    """Tailoring must extend the original profile, not replace it."""
    xml = build_tailoring_xml(_profile({_RULE_TELNET: True}))
    prof = ET.fromstring(xml).find(f"{{{XCCDF_NS}}}Profile")
    assert prof.get("extends") == _BASE_PROFILE
    assert prof.get("id") == TAILORED_PROFILE_ID


def test_benchmark_href_points_at_the_datastream():
    xml = build_tailoring_xml(_profile({_RULE_TELNET: True}))
    bench = ET.fromstring(xml).find(f"{{{XCCDF_NS}}}benchmark")
    assert bench.get("href").endswith("ssg-ubuntu2204-ds.xml")


def test_justification_is_preserved_in_the_artifact():
    """The waiver reason must survive into the file an auditor reads."""
    reason = "Ubuntu uses AppArmor as the MAC framework."
    xml = build_tailoring_xml(_profile({_RULE_SELINUX: {"enabled": False, "justification": reason}}))
    assert reason in xml
    # and summarised in the machine-readable description
    desc = ET.fromstring(xml).find(f"{{{XCCDF_NS}}}Profile/{{{XCCDF_NS}}}description")
    assert _RULE_SELINUX in desc.text


def test_generated_xml_is_wellformed_and_namespaced():
    xml = build_tailoring_xml(_profile({_RULE_SELINUX: {"enabled": False, "justification": "x"}}))
    root = ET.fromstring(xml)  # raises if malformed
    assert root.tag == f"{{{XCCDF_NS}}}Tailoring"


def test_justification_with_xml_metacharacters_is_escaped():
    """A justification is free text; it must not be able to break the document."""
    xml = build_tailoring_xml(_profile({_RULE_TELNET: {"enabled": False, "justification": "a < b & c > d"}}))
    ET.fromstring(xml)  # must still parse
    assert _selects(xml)[_RULE_TELNET] == "false"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_write_returns_none_without_controls(tmp_path: Path):
    assert write_tailoring(_profile(), tmp_path) is None


def test_write_creates_file(tmp_path: Path):
    path = write_tailoring(_profile({_RULE_TELNET: True}), tmp_path)
    assert path is not None and path.exists()
    ET.fromstring(path.read_text())


# ---------------------------------------------------------------------------
# Scanner wiring — the part that makes the override actually take effect
# ---------------------------------------------------------------------------


def test_command_without_tailoring_uses_original_profile():
    cmd = _build_command(_profile(), None, "root", Path("/tmp/a.xml"), Path("/tmp/r.html"), None)
    assert "--tailoring-file" not in cmd
    assert cmd[cmd.index("--profile") + 1] == _BASE_PROFILE


def test_command_with_tailoring_switches_to_tailored_profile():
    """Passing the original profile ID alongside a tailoring file silently ignores it."""
    tf = Path("/tmp/bakex-tailoring.xml")
    cmd = _build_command(_profile(), None, "root", Path("/tmp/a.xml"), Path("/tmp/r.html"), tf)
    assert cmd[cmd.index("--profile") + 1] == TAILORED_PROFILE_ID
    assert cmd[cmd.index("--tailoring-file") + 1] == str(tf)


def test_tailoring_flag_precedes_the_datastream_positional():
    """oscap takes the datastream as the trailing positional; flags must come before it."""
    tf = Path("/tmp/bakex-tailoring.xml")
    cmd = _build_command(_profile(), None, "root", Path("/tmp/a.xml"), Path("/tmp/r.html"), tf)
    assert cmd.index("--tailoring-file") < len(cmd) - 1
    assert cmd[-1].endswith("-ds.xml")
