# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for ComplianceProfile schema validation and YAML loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from bakex.core.blueprint import (
    ComplianceProfile,
    ControlOverride,
    ProfileMetadata,
    load_profile,
)

EXAMPLE_PROFILE = Path("profiles/examples/ubuntu22_cis_l1.yaml")

MINIMAL_PROFILE = {
    "bakex_version": "0.1.0",
    "kind": "ComplianceProfile",
    "metadata": {
        "name": "test-profile",
        "version": "1.0.0",
    },
    "target": {
        "os": "ubuntu22.04",
        "provider": "local",
        "base_image": "ubuntu/jammy64",
    },
    "compliance": {
        "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU2204",
        "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
        "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
    },
}


def test_minimal_profile_parses():
    profile = ComplianceProfile.model_validate(MINIMAL_PROFILE)
    assert profile.metadata.name == "test-profile"
    assert profile.kind == "ComplianceProfile"
    assert profile.target.provider == "local"


def test_controls_bool():
    data = {**MINIMAL_PROFILE, "controls": {"some_rule_id": True}}
    profile = ComplianceProfile.model_validate(data)
    assert profile.controls["some_rule_id"] is True


def test_controls_override_object():
    data = {
        **MINIMAL_PROFILE,
        "controls": {"some_rule_id": {"enabled": False, "justification": "Not applicable here"}},
    }
    profile = ComplianceProfile.model_validate(data)
    override = profile.controls["some_rule_id"]
    assert isinstance(override, ControlOverride)
    assert override.enabled is False
    assert "Not applicable" in override.justification


def test_invalid_kind_rejected():
    bad = {**MINIMAL_PROFILE, "kind": "SomethingElse"}
    with pytest.raises(Exception):
        ComplianceProfile.model_validate(bad)


def test_load_example_profile():
    if not EXAMPLE_PROFILE.exists():
        pytest.skip("Example profile not found (run from repo root)")
    profile = load_profile(EXAMPLE_PROFILE)
    assert profile.metadata.name == "ubuntu22-cis-l1"
    assert profile.target.os == "ubuntu22.04"
    assert profile.compliance.fail_on_findings is True


def test_load_profile_missing_file():
    with pytest.raises(FileNotFoundError):
        load_profile(Path("/nonexistent/profile.yaml"))


def test_profile_metadata_defaults():
    m = ProfileMetadata(name="foo", version="1.0")
    assert m.description == ""
    assert m.tags == []
