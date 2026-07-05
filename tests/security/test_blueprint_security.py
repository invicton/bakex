# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Security tests for blueprint input sanitization (SEC-08–SEC-10).

These tests verify that malicious inputs are handled safely at the Pydantic
schema boundary — before they can reach subprocess calls or file system ops.
"""

from __future__ import annotations

from pydantic import ValidationError

from stratum.core.blueprint import ComplianceProfile


def _minimal_profile(**overrides) -> dict:
    """Return a minimal valid blueprint dict, with optional field overrides."""
    base = {
        "stratum_version": "0.2.0",
        "kind": "HardeningBlueprint",
        "metadata": {
            "name": "test-sec",
            "version": "1.0.0",
            "description": "",
        },
        "target": {
            "os": "ubuntu22.04",
            "provider": "aws",
            "base_image": "ami-12345678",
            "instance_type": "t3.medium",
        },
        "compliance": {
            "benchmark": "xccdf_org.ssgproject.content_benchmark_UBUNTU22",
            "profile": "xccdf_org.ssgproject.content_profile_cis_level1_server",
            "datastream": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# SEC-08: Shell metacharacters in base_image are accepted as strings
# ---------------------------------------------------------------------------


def test_shell_metacharacters_in_base_image_accepted_as_string():
    """Pydantic must accept shell metacharacters in base_image as a raw string.
    Sanitization is the provider's responsibility — the schema must not crash.
    """
    malicious = "ami-12345678; rm -rf /"
    data = _minimal_profile()
    data["target"]["base_image"] = malicious

    profile = ComplianceProfile.model_validate(data)
    assert profile.target.base_image == malicious, (
        "Shell metacharacters must be stored as-is — provider must sanitize before subprocess call"
    )


# ---------------------------------------------------------------------------
# SEC-09: Path traversal in datastream is accepted as a string
# ---------------------------------------------------------------------------


def test_path_traversal_in_datastream_accepted_as_string():
    """Pydantic must accept a path-traversal string in the datastream field.
    The scanner/provider is responsible for path validation before execution.
    """
    traversal = "../../etc/passwd"
    data = _minimal_profile()
    data["compliance"]["datastream"] = traversal

    profile = ComplianceProfile.model_validate(data)
    assert profile.compliance.datastream == traversal, (
        "Path traversal string must be stored as-is — scanner must validate path before use"
    )


# ---------------------------------------------------------------------------
# SEC-10: Null bytes in metadata.name — ValidationError or stripped silently
# ---------------------------------------------------------------------------


def test_null_bytes_in_metadata_name_handled_safely():
    """Null bytes in metadata.name must either be rejected (ValidationError)
    or silently stripped. They must never be passed through to a subprocess.
    """
    data = _minimal_profile()
    data["metadata"]["name"] = "evil\x00name"

    try:
        profile = ComplianceProfile.model_validate(data)
        # If accepted: verify the null byte is NOT present in the stored value
        stored_name = profile.metadata.name
        assert "\x00" not in stored_name, "Null byte survived Pydantic validation and would reach subprocess calls"
    except (ValidationError, ValueError):
        # ValidationError is the preferred outcome — explicit rejection is safest
        pass


# ---------------------------------------------------------------------------
# SEC-11: Path traversal in metadata.name must be rejected — this value is
# used to build a filesystem path (`user_profiles_dir / f"{name}.yaml"`) in
# stratum/api/blueprints.py::upload_blueprint.
# ---------------------------------------------------------------------------


def test_path_traversal_in_metadata_name_rejected():
    for traversal in ("../../../../tmp/evil", "..\\..\\evil", "/etc/cron.d/evil", "a/b", "..", "."):
        data = _minimal_profile()
        data["metadata"]["name"] = traversal
        try:
            ComplianceProfile.model_validate(data)
            raise AssertionError(f"expected ValidationError for metadata.name={traversal!r}")
        except ValidationError:
            pass


def test_normal_metadata_names_still_accepted():
    for name in ("ubuntu22-cis-l1-aws", "rocky9_cis-l2", "my.profile.v1"):
        data = _minimal_profile()
        data["metadata"]["name"] = name
        profile = ComplianceProfile.model_validate(data)
        assert profile.metadata.name == name
