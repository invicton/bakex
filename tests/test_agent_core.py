# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for bakex/core/agent.py tool implementations and agent loop.

Tests use mocked LLM backends so no API key is required.

Coverage targets:
  _apply_required_defaults, _validate_blueprint, _enrich_blueprint,
  _start_build, _get_build_status, _get_scan_report,
  _analyze_findings, _retry_build_yaml, _execute_tool,
  run_build_agent (end_turn + tool_use loops, error paths)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from bakex.core.agent import (
    _analyze_findings,
    _apply_required_defaults,
    _enrich_blueprint,
    _execute_tool,
    _get_build_status,
    _get_scan_report,
    _retry_build_yaml,
    _start_build,
    _validate_blueprint,
    run_build_agent,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_VALID_YAML = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: agent-test-profile
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""

_INVALID_YAML = "not: valid: yaml: ["

_MISSING_COMPLIANCE_YAML = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: agent-no-compliance
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
"""


# ---------------------------------------------------------------------------
# _apply_required_defaults
# ---------------------------------------------------------------------------


def test_apply_required_defaults_sets_missing_keys():
    raw: dict = {}
    result = _apply_required_defaults(raw)
    assert result["bakex_version"] == "1"
    assert result["kind"] == "HardeningBlueprint"


def test_apply_required_defaults_does_not_overwrite_existing():
    raw = {"bakex_version": "0.2.0", "kind": "ComplianceProfile"}
    _apply_required_defaults(raw)
    assert raw["bakex_version"] == "0.2.0"
    assert raw["kind"] == "ComplianceProfile"


# ---------------------------------------------------------------------------
# _validate_blueprint
# ---------------------------------------------------------------------------


def test_validate_blueprint_valid_yaml_returns_valid_true():
    result = _validate_blueprint(_VALID_YAML)
    assert result["valid"] is True
    assert result["profile_name"] == "agent-test-profile"
    assert result["os"] == "ubuntu22.04"
    assert result["provider"] == "aws"
    assert "benchmark" in result


def test_validate_blueprint_malformed_yaml_returns_valid_false():
    result = _validate_blueprint("key: [not valid {{")
    assert result["valid"] is False
    assert "error" in result


def test_validate_blueprint_missing_compliance_returns_valid_false():
    result = _validate_blueprint(_MISSING_COMPLIANCE_YAML)
    assert result["valid"] is False
    assert "error" in result


def test_validate_blueprint_non_mapping_yaml_returns_valid_false():
    result = _validate_blueprint("- item1\n- item2\n")
    assert result["valid"] is False
    assert "not a YAML mapping" in result["error"].lower() or "error" in result


# ---------------------------------------------------------------------------
# _enrich_blueprint
# ---------------------------------------------------------------------------


def test_enrich_blueprint_sets_instance_type_for_aws():
    minimal = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: enrich-test
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00000000
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""
    result = _enrich_blueprint(minimal, "aws")
    assert "enriched_yaml" in result
    enriched = yaml.safe_load(result["enriched_yaml"])
    assert enriched["target"]["instance_type"] == "t3.medium"
    assert enriched["target"]["root_volume_size_gb"] == 20


def test_enrich_blueprint_sets_provider_when_missing():
    raw = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: enrich-no-provider
  version: "1.0.0"
target:
  os: ubuntu22.04
  base_image: ami-00
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""
    result = _enrich_blueprint(raw, "gcp")
    assert "enriched_yaml" in result
    enriched = yaml.safe_load(result["enriched_yaml"])
    assert enriched["target"]["provider"] == "gcp"
    changes = result.get("changes", [])
    assert any("provider" in c.lower() for c in changes)


def test_enrich_blueprint_sets_datastream_for_ubuntu():
    raw = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: enrich-ds
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: aws
  base_image: ami-00
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: auto
"""
    result = _enrich_blueprint(raw, "aws")
    assert "enriched_yaml" in result
    enriched = yaml.safe_load(result["enriched_yaml"])
    assert "ubuntu2204" in enriched["compliance"]["datastream"]


def test_enrich_blueprint_sets_datastream_for_rocky():
    raw = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: enrich-rocky-ds
  version: "1.0.0"
target:
  os: rocky9
  provider: aws
  base_image: ami-00
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_RHEL-9
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: auto
"""
    result = _enrich_blueprint(raw, "aws")
    assert "enriched_yaml" in result
    enriched = yaml.safe_load(result["enriched_yaml"])
    assert "rhel9" in enriched["compliance"]["datastream"]


def test_enrich_blueprint_malformed_yaml_returns_error():
    result = _enrich_blueprint("key: [bad {{", "aws")
    assert "error" in result


def test_enrich_blueprint_provider_specific_instance_types():
    """Verify each supported provider gets a meaningful instance type."""
    base = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: enrich-providers
  version: "1.0.0"
target:
  os: ubuntu22.04
  provider: auto
  base_image: ami-00
compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_UBUNTU2204
  profile: xccdf_org.ssgproject.content_profile_cis_level1_server
  datastream: /usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml
"""
    expected = {
        "gcp": "n2-standard-2",
        "azure": "Standard_D2s_v3",
        "digitalocean": "s-2vcpu-2gb",
        "linode": "g6-standard-2",
    }
    for provider, expected_type in expected.items():
        result = _enrich_blueprint(base, provider)
        assert "enriched_yaml" in result, f"Expected enriched_yaml for {provider}"
        enriched = yaml.safe_load(result["enriched_yaml"])
        assert enriched["target"]["instance_type"] == expected_type, (
            f"Provider {provider}: expected {expected_type}, got {enriched['target']['instance_type']}"
        )


# ---------------------------------------------------------------------------
# _analyze_findings
# ---------------------------------------------------------------------------


def test_analyze_findings_empty_list():
    result = _analyze_findings("[]")
    assert result["count"] == 0
    assert "0 failed rules" in result["summary"]


def test_analyze_findings_groups_by_severity():
    findings = json.dumps(
        [
            {"id": "r1", "title": "Root login", "severity": "high"},
            {"id": "r2", "title": "SSH config", "severity": "high"},
            {"id": "r3", "title": "Auditd", "severity": "medium"},
            {"id": "r4", "title": "Firewall", "severity": "critical"},
        ]
    )
    result = _analyze_findings(findings)
    assert result["count"] == 4
    assert result["by_severity"]["high"] == 2
    assert result["by_severity"]["medium"] == 1
    assert result["by_severity"]["critical"] == 1
    assert "HIGH" in result["summary"]
    assert "CRITICAL" in result["summary"]


def test_analyze_findings_invalid_json_returns_error():
    result = _analyze_findings("{not valid json")
    assert "error" in result


def test_analyze_findings_non_list_json_returns_error():
    result = _analyze_findings('{"rule": "not a list"}')
    assert "error" in result


def test_analyze_findings_truncates_long_lists():
    """More than 10 findings per severity should show '... and N more'."""
    findings = json.dumps([{"id": f"rule_{i}", "title": f"Rule {i}", "severity": "medium"} for i in range(15)])
    result = _analyze_findings(findings)
    assert "more" in result["summary"]
    assert result["count"] == 15


def test_analyze_findings_unknown_severity():
    findings = json.dumps([{"id": "r1", "severity": None}])
    result = _analyze_findings(findings)
    assert result["count"] == 1


# ---------------------------------------------------------------------------
# _retry_build_yaml
# ---------------------------------------------------------------------------


def test_retry_build_yaml_with_valid_replacement_yaml():
    new_yaml = _VALID_YAML
    result = _retry_build_yaml(_VALID_YAML, new_yaml)
    assert "updated_yaml" in result
    assert result["updated_yaml"] == new_yaml
    assert "applied" in result


def test_retry_build_yaml_with_invalid_modifications_falls_back():
    result = _retry_build_yaml(_VALID_YAML, "some plain text instructions")
    assert "updated_yaml" in result
    # Falls back to original when modifications cannot be applied
    assert result["updated_yaml"] == _VALID_YAML


def test_retry_build_yaml_with_non_dict_yaml_falls_back():
    result = _retry_build_yaml(_VALID_YAML, "- item1\n- item2\n")
    assert "updated_yaml" in result


# ---------------------------------------------------------------------------
# _get_build_status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_build_status_returns_pending_for_known_job():
    from bakex.core import builder as bs
    from bakex.core.builder import BuildJob

    job = BuildJob(profile_name="test", provider_name="aws")
    bs._jobs[job.id] = job

    result = await _get_build_status(job.id)
    assert result["job_id"] == job.id
    assert result["status"] == "pending"
    assert result["done"] is False

    del bs._jobs[job.id]


@pytest.mark.anyio
async def test_get_build_status_returns_error_for_unknown_job():
    result = await _get_build_status("nonexistent-job-id-xyz")
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.anyio
async def test_get_build_status_complete_job_shows_artifact():
    from bakex.core import builder as bs
    from bakex.core.builder import BuildJob, BuildStatus
    from bakex.plugins.base_provider import ProviderResult

    job = BuildJob(profile_name="test", provider_name="aws")
    job.status = BuildStatus.COMPLETE
    job.result = ProviderResult(artifact_id="ami-test-agent-001", artifact_type="ami")
    bs._jobs[job.id] = job

    result = await _get_build_status(job.id)
    assert result["done"] is True
    assert result["artifact_id"] == "ami-test-agent-001"

    del bs._jobs[job.id]


# ---------------------------------------------------------------------------
# _get_scan_report
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_scan_report_unknown_job_returns_error():
    result = await _get_scan_report("nonexistent-build-job")
    assert "error" in result


@pytest.mark.anyio
async def test_get_scan_report_incomplete_job_returns_error():
    from bakex.core import builder as bs
    from bakex.core.builder import BuildJob, BuildStatus

    job = BuildJob(profile_name="test", provider_name="aws")
    # Leave as PENDING (not complete)
    assert job.status == BuildStatus.PENDING
    bs._jobs[job.id] = job

    result = await _get_scan_report(job.id)
    assert "error" in result
    assert "not complete" in result["error"].lower()

    del bs._jobs[job.id]


@pytest.mark.anyio
async def test_get_scan_report_complete_job_returns_artifact():
    from bakex.core import builder as bs
    from bakex.core.builder import BuildJob, BuildStatus
    from bakex.plugins.base_provider import ProviderResult

    job = BuildJob(profile_name="test", provider_name="aws")
    job.status = BuildStatus.COMPLETE
    job.result = ProviderResult(artifact_id="ami-scan-test-001", artifact_type="ami", region="us-east-1")
    bs._jobs[job.id] = job

    result = await _get_scan_report(job.id)
    assert result["artifact_id"] == "ami-scan-test-001"
    assert result["provider"] == "aws"
    assert "message" in result

    del bs._jobs[job.id]


# ---------------------------------------------------------------------------
# _start_build (mocked to avoid real cloud calls)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_start_build_creates_job():
    with patch("bakex.core.agent.asyncio.create_task"):
        result = await _start_build(_VALID_YAML, "aws")
    assert "job_id" in result
    assert result["status"] == "pending"


@pytest.mark.anyio
async def test_start_build_invalid_yaml_returns_error():
    with patch("bakex.core.agent.asyncio.create_task"):
        result = await _start_build("not: [valid: yaml{{{", "aws")
    assert "error" in result


# ---------------------------------------------------------------------------
# _execute_tool dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_execute_tool_validate_blueprint():
    result = await _execute_tool("validate_blueprint", {"yaml_text": _VALID_YAML})
    assert result["valid"] is True


@pytest.mark.anyio
async def test_execute_tool_enrich_blueprint():
    result = await _execute_tool("enrich_blueprint", {"yaml_text": _VALID_YAML, "provider": "aws"})
    assert "enriched_yaml" in result


@pytest.mark.anyio
async def test_execute_tool_analyze_findings():
    findings = json.dumps([{"id": "r1", "severity": "high", "title": "Test"}])
    result = await _execute_tool("analyze_findings", {"findings_json": findings})
    assert result["count"] == 1


@pytest.mark.anyio
async def test_execute_tool_retry_build():
    result = await _execute_tool("retry_build", {"yaml_text": _VALID_YAML, "modifications": _VALID_YAML})
    assert "updated_yaml" in result


@pytest.mark.anyio
async def test_execute_tool_get_build_status_unknown():
    result = await _execute_tool("get_build_status", {"job_id": "no-such-job"})
    assert "error" in result


@pytest.mark.anyio
async def test_execute_tool_unknown_tool_returns_error():
    result = await _execute_tool("nonexistent_tool", {})
    assert "error" in result
    assert "Unknown tool" in result["error"]


@pytest.mark.anyio
async def test_execute_tool_start_build_blocked_by_default(monkeypatch):
    """With BAKEX_AGENT_REQUIRE_CONFIRMATION at its default (true), the agent
    must not be able to trigger a real cloud build without a human clicking
    Build in the UI first."""
    from bakex.config import settings

    monkeypatch.setattr(settings, "bakex_agent_require_confirmation", True)
    with patch("bakex.core.agent._start_build", new_callable=AsyncMock) as mock_start:
        result = await _execute_tool("start_build", {"yaml_text": _VALID_YAML, "provider": "aws"})
    mock_start.assert_not_called()
    assert "error" in result
    assert "BAKEX_AGENT_REQUIRE_CONFIRMATION" in result["error"]


@pytest.mark.anyio
async def test_execute_tool_start_build_allowed_when_confirmation_disabled(monkeypatch):
    from bakex.config import settings

    monkeypatch.setattr(settings, "bakex_agent_require_confirmation", False)
    with patch(
        "bakex.core.agent._start_build",
        new_callable=AsyncMock,
        return_value={"job_id": "jb-1", "status": "pending"},
    ) as mock_start:
        result = await _execute_tool("start_build", {"yaml_text": _VALID_YAML, "provider": "aws"})
    mock_start.assert_called_once_with(yaml_text=_VALID_YAML, provider="aws")
    assert result == {"job_id": "jb-1", "status": "pending"}


# ---------------------------------------------------------------------------
# run_build_agent — mocked LLM backend
# ---------------------------------------------------------------------------


def _make_mock_backend(turns: list) -> MagicMock:
    """Build a mock backend that returns pre-configured turns."""

    backend = MagicMock()
    turn_iter = iter(turns)

    async def _agent_turn(messages, tools, system, max_tokens, on_token):
        await on_token("narration chunk")
        return next(turn_iter)

    backend.agent_turn = _agent_turn
    return backend


@pytest.mark.anyio
async def test_run_build_agent_end_turn_success():
    """Agent completes in one turn (end_turn) — success path."""
    from bakex.core.llm.base import AgentTurnResult, TextBlock

    turn = AgentTurnResult(
        stop_reason="end_turn",
        content=[TextBlock(text="Build complete.\nArtifact: ami-final-001\nGrade: A\nScore: 96%")],
    )

    tokens: list[str] = []

    async def on_token(t: str):
        tokens.append(t)

    mock_backend = _make_mock_backend([turn])

    with patch("bakex.core.llm.get_backend", return_value=mock_backend):
        result = await run_build_agent(_VALID_YAML, "aws", on_token)

    assert result.success is True
    assert result.artifact_id == "ami-final-001"
    assert len(tokens) > 0


@pytest.mark.anyio
async def test_run_build_agent_backend_unavailable_returns_error():
    """If get_backend raises, agent returns failure immediately."""
    tokens: list[str] = []

    async def on_token(t: str):
        tokens.append(t)

    with patch("bakex.core.llm.get_backend", side_effect=RuntimeError("No API key")):
        result = await run_build_agent(_VALID_YAML, "aws", on_token)

    assert result.success is False
    assert "No API key" in result.error
    assert any("ERROR" in t for t in tokens)


@pytest.mark.anyio
async def test_run_build_agent_unexpected_stop_reason_returns_error():
    """Unexpected stop_reason (not end_turn, not tool_use) aborts the loop."""
    from bakex.core.llm.base import AgentTurnResult

    turn = AgentTurnResult(stop_reason="max_tokens", content=[])
    mock_backend = _make_mock_backend([turn])

    async def on_token(t: str):
        pass

    with patch("bakex.core.llm.get_backend", return_value=mock_backend):
        result = await run_build_agent(_VALID_YAML, "aws", on_token)

    assert result.success is False
    assert "max_tokens" in result.error


@pytest.mark.anyio
async def test_run_build_agent_tool_use_then_end_turn():
    """Agent makes a tool call, gets result, then ends the turn."""
    from bakex.core.llm.base import AgentTurnResult, TextBlock, ToolUseBlock

    tool_turn = AgentTurnResult(
        stop_reason="tool_use",
        content=[
            ToolUseBlock(
                id="tool-001",
                name="validate_blueprint",
                input={"yaml_text": _VALID_YAML},
            )
        ],
    )
    end_turn = AgentTurnResult(
        stop_reason="end_turn",
        content=[TextBlock(text="Blueprint validated.\nArtifact: ami-tool-test\nGrade: B\nDone.")],
    )

    narration: list[str] = []

    async def on_token(t: str):
        narration.append(t)

    mock_backend = _make_mock_backend([tool_turn, end_turn])

    with patch("bakex.core.llm.get_backend", return_value=mock_backend):
        result = await run_build_agent(_VALID_YAML, "aws", on_token)

    assert result.success is True
    assert result.artifact_id == "ami-tool-test"
    assert any("validate_blueprint" in t for t in narration)


@pytest.mark.anyio
async def test_run_build_agent_tool_exception_is_caught():
    """Tool execution exception must not crash the agent — it returns an error dict."""
    from bakex.core.llm.base import AgentTurnResult, TextBlock, ToolUseBlock

    tool_turn = AgentTurnResult(
        stop_reason="tool_use",
        content=[
            ToolUseBlock(
                id="tool-002",
                name="start_build",
                input={"yaml_text": _VALID_YAML, "provider": "aws"},
            )
        ],
    )
    end_turn = AgentTurnResult(
        stop_reason="end_turn",
        content=[TextBlock(text="Handled error gracefully.")],
    )

    async def on_token(t: str):
        pass

    mock_backend = _make_mock_backend([tool_turn, end_turn])

    with (
        patch("bakex.core.llm.get_backend", return_value=mock_backend),
        patch("bakex.core.agent._execute_tool", side_effect=RuntimeError("cloud error")),
    ):
        result = await run_build_agent(_VALID_YAML, "aws", on_token)

    # Agent should not crash — end_turn still reached
    assert result.error == "" or "cloud error" not in result.error


@pytest.mark.anyio
async def test_run_build_agent_records_job_id_from_start_build():
    """job_id extracted from start_build tool result is stored on AgentResult."""
    from bakex.core.llm.base import AgentTurnResult, TextBlock, ToolUseBlock

    tool_turn = AgentTurnResult(
        stop_reason="tool_use",
        content=[
            ToolUseBlock(
                id="tool-003",
                name="start_build",
                input={"yaml_text": _VALID_YAML, "provider": "aws"},
            )
        ],
    )
    end_turn = AgentTurnResult(
        stop_reason="end_turn",
        content=[TextBlock(text="Build started. Artifact: ami-job-id-test. Grade: A.")],
    )

    async def on_token(t: str):
        pass

    mock_backend = _make_mock_backend([tool_turn, end_turn])

    with (
        patch("bakex.core.llm.get_backend", return_value=mock_backend),
        patch("bakex.core.agent._execute_tool", return_value={"job_id": "jb-abc-123", "status": "pending"}),
    ):
        result = await run_build_agent(_VALID_YAML, "aws", on_token)

    assert result.job_id == "jb-abc-123"


# ---------------------------------------------------------------------------
# /api/agent/status and /api/agent/build endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def _agent_client(monkeypatch):
    """Minimal TestClient for agent endpoint tests (no profile dir needed)."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from bakex.config import settings

    monkeypatch.setattr(settings, "bakex_admin_token", "test-admin-token")

    with patch("bakex.core.registry.init_registry"):
        from bakex.main import app

        with TestClient(app, raise_server_exceptions=True) as c:
            c.auth = ("admin", "test-admin-token")
            yield c


def test_agent_status_returns_available_false_without_key(_agent_client):
    """Without ANTHROPIC_API_KEY the status must show available=false."""
    import os

    env_backup = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        resp = _agent_client.get("/api/agent/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "available" in body
        assert body["available"] is False
    finally:
        if env_backup is not None:
            os.environ["ANTHROPIC_API_KEY"] = env_backup


def test_agent_build_returns_400_when_provider_unavailable(_agent_client):
    """POST /api/agent/build must 400 when the configured LLM provider has no key."""
    import os

    env_backup = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        resp = _agent_client.post(
            "/api/agent/build",
            json={
                "blueprint_yaml": _VALID_YAML,
                "provider": "aws",
            },
        )
        assert resp.status_code == 400
    finally:
        if env_backup is not None:
            os.environ["ANTHROPIC_API_KEY"] = env_backup


def test_agent_build_returns_400_for_empty_blueprint(_agent_client):
    """POST /api/agent/build with empty blueprint_yaml must 400."""
    import os

    os.environ["ANTHROPIC_API_KEY"] = "sk-test-fake"
    try:
        resp = _agent_client.post(
            "/api/agent/build",
            json={
                "blueprint_yaml": "   ",
                "provider": "aws",
            },
        )
        assert resp.status_code == 400
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
