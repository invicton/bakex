# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Compile a blueprint's ``controls`` block into an XCCDF 1.2 tailoring file.

A blueprint can override individual benchmark rules::

    controls:
      xccdf_org.ssgproject.content_rule_grub2_enable_selinux:
        enabled: false
        justification: Ubuntu uses AppArmor; SELinux is not applicable.
      xccdf_org.ssgproject.content_rule_package_telnet_removed: true

Until now that block was inert — it was rendered in the UI and never reached the scanner,
so a disabled rule was still evaluated, still failed, and still counted against the grade.
The perverse result was that documenting a genuinely non-applicable rule *lowered* your
score, while staying silent did not.

This module turns those declarations into a tailoring file that ``oscap`` understands, so
the override actually takes effect. Rules the blueprint disables are deselected and are not
evaluated; rules it explicitly enables are selected.

Justifications ride along as XML comments next to each ``select`` and are summarised in the
profile description. That is deliberate: XCCDF has no per-select justification attribute,
and the reason a rule was waived belongs with the artifact an auditor reads, not only in
the blueprint that produced it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from bakex.core.blueprint import ComplianceProfile, ControlOverride

logger = logging.getLogger(__name__)

XCCDF_NS = "http://checklists.nist.gov/xccdf/1.2"

#: ID of the tailoring document itself.
TAILORING_ID = "xccdf_com.bakex_tailoring_blueprint"

#: ID of the generated profile. ``oscap --profile`` must reference *this*, not the
#: blueprint's original profile, or the tailoring is silently ignored.
TAILORED_PROFILE_ID = "xccdf_com.bakex_profile_tailored"


def _normalise(controls: dict[str, bool | ControlOverride]) -> list[tuple[str, bool, str]]:
    """Flatten the two accepted shapes into ``(rule_id, enabled, justification)``."""
    out: list[tuple[str, bool, str]] = []
    for rule_id, override in controls.items():
        if isinstance(override, bool):
            out.append((rule_id, override, ""))
        else:
            out.append((rule_id, override.enabled, override.justification or ""))
    return out


def build_tailoring_xml(profile: ComplianceProfile) -> str | None:
    """Return the tailoring XML for *profile*, or ``None`` if it declares no controls.

    Returning ``None`` keeps the no-controls path byte-identical to an untailored scan —
    we do not want to change how the vast majority of blueprints are evaluated.
    """
    entries = _normalise(profile.controls)
    if not entries:
        return None

    ET.register_namespace("xccdf", XCCDF_NS)
    q = lambda tag: f"{{{XCCDF_NS}}}{tag}"  # noqa: E731

    root = ET.Element(q("Tailoring"), {"id": TAILORING_ID})
    ET.SubElement(root, q("benchmark"), {"href": profile.compliance.datastream})

    version = ET.SubElement(root, q("version"), {"time": datetime.now(UTC).isoformat()})
    version.text = "1"

    prof = ET.SubElement(
        root,
        q("Profile"),
        {"id": TAILORED_PROFILE_ID, "extends": profile.compliance.profile},
    )
    title = ET.SubElement(prof, q("title"))
    title.text = f"BakeX tailored profile for {profile.metadata.name}"

    disabled = [(r, j) for r, enabled, j in entries if not enabled]
    desc = ET.SubElement(prof, q("description"))
    if disabled:
        reasons = "; ".join(f"{rule}: {just or 'no justification recorded'}" for rule, just in disabled)
        desc.text = f"Generated from blueprint '{profile.metadata.name}'. Waived rules — {reasons}"
    else:
        desc.text = f"Generated from blueprint '{profile.metadata.name}'. No rules waived."

    for rule_id, enabled, justification in entries:
        if justification:
            # Keep the reason adjacent to the decision in the artifact an auditor reads.
            prof.append(ET.Comment(f" {rule_id}: {justification.strip()} "))
        ET.SubElement(
            prof,
            q("select"),
            {"idref": rule_id, "selected": "true" if enabled else "false"},
        )

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def write_tailoring(profile: ComplianceProfile, output_dir: Path) -> Path | None:
    """Write the tailoring file for *profile* into *output_dir*.

    Returns the path, or ``None`` when the blueprint declares no control overrides.
    """
    xml = build_tailoring_xml(profile)
    if xml is None:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "bakex-tailoring.xml"
    path.write_text(xml, encoding="utf-8")

    waived = sum(1 for _, enabled, _ in _normalise(profile.controls) if not enabled)
    logger.info(
        "Wrote OpenSCAP tailoring to %s (%d rule override(s), %d waived)",
        path,
        len(profile.controls),
        waived,
    )
    return path
