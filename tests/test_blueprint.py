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


# ---------------------------------------------------------------------------
# OS ↔ provider compatibility
# ---------------------------------------------------------------------------


def _with_target(**target_overrides) -> dict:
    return {**MINIMAL_PROFILE, "target": {**MINIMAL_PROFILE["target"], **target_overrides}}


def test_catalogued_os_provider_pair_accepted():
    profile = ComplianceProfile.model_validate(
        _with_target(os="alma9", provider="gcp", base_image="family/almalinux-9")
    )
    assert profile.target.provider == "gcp"


def test_incompatible_catalogued_pair_rejected():
    """Amazon Linux 2023 is AWS-only — pairing it with GCP must fail."""
    with pytest.raises(ValueError, match="not supported for os 'amazon-linux-2023'"):
        ComplianceProfile.model_validate(_with_target(os="amazon-linux-2023", provider="gcp", base_image="whatever"))


def test_rejection_message_lists_supported_providers():
    with pytest.raises(ValueError, match="Supported providers: aws"):
        ComplianceProfile.model_validate(_with_target(os="amazon-linux-2023", provider="azure", base_image="whatever"))


def test_uncatalogued_provider_allowed():
    """Providers are pluggable via the `bakex.providers` entry-point group, so an
    unknown provider name is not ours to reject — only the registry can say."""
    profile = ComplianceProfile.model_validate(_with_target(os="ubuntu22.04", provider="mycloud", base_image="img-1"))
    assert profile.target.provider == "mycloud"


def test_uncatalogued_os_allowed():
    """The shipped generic blueprint targets `generic-linux` — we hold no opinion."""
    profile = ComplianceProfile.model_validate(
        _with_target(os="generic-linux", provider="aws", base_image="ami-placeholder")
    )
    assert profile.target.os == "generic-linux"
