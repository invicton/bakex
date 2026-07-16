# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tests for the SSE-streaming /api/agent/build endpoint.

Covers api/agent.py lines 43-90 (event_stream inner function):
  - narration tokens arrive as data: {"type":"narration",...} events
  - final result arrives as data: {"type":"result",...} event
  - exception inside run_build_agent produces data: {"type":"error",...}
  - 400 when LLM provider is unavailable
  - 400 when blueprint_yaml is empty
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from bakex.core.agent import AgentResult

# ---------------------------------------------------------------------------
# Shared YAML fixture
# ---------------------------------------------------------------------------

_VALID_YAML = """\
bakex_version: "0.1.0"
kind: ComplianceProfile
metadata:
  name: sse-test-profile
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


def _parse_sse_events(body: bytes) -> list[dict]:
    """Parse raw SSE bytes into a list of event payload dicts."""
    events = []
    for line in body.decode().splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_agent_build_provider_unavailable_returns_400(client):
    """When the LLM provider has no credentials, endpoint returns 400."""
    with patch("bakex.api.agent.provider_status", return_value={"available": False, "message": "No API key"}):
        resp = client.post("/api/agent/build", json={"blueprint_yaml": _VALID_YAML, "provider": "aws"})
    assert resp.status_code == 400
    assert "No API key" in resp.json()["detail"]


def test_agent_build_empty_yaml_returns_400(client):
    """Empty blueprint_yaml returns 400 immediately."""
    with patch("bakex.api.agent.provider_status", return_value={"available": True, "message": "ok"}):
        resp = client.post("/api/agent/build", json={"blueprint_yaml": "   ", "provider": "aws"})
    assert resp.status_code == 400
    assert "blueprint_yaml is required" in resp.json()["detail"]


@pytest.mark.anyio
async def test_agent_build_sse_streams_narration_and_result(client):
    """The SSE stream emits narration events then a final result event."""
    mock_result = AgentResult(
        success=True,
        artifact_id="ami-sse-001",
        grade="A",
        score_pct=95.0,
        summary="Build complete",
        error=None,
        retries_used=0,
        job_id="job-sse-001",
        final_blueprint_yaml=_VALID_YAML,
    )

    async def fake_run_build_agent(blueprint_yaml, provider, on_token):
        await on_token("Building...")
        await on_token("Done.")
        return mock_result

    with patch("bakex.api.agent.provider_status", return_value={"available": True, "message": "ok"}):
        with patch("bakex.api.agent.run_build_agent", side_effect=fake_run_build_agent):
            resp = client.post(
                "/api/agent/build",
                json={"blueprint_yaml": _VALID_YAML, "provider": "aws"},
            )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = _parse_sse_events(resp.content)
    narration_events = [e for e in events if e.get("type") == "narration"]
    result_events = [e for e in events if e.get("type") == "result"]

    assert len(narration_events) == 2
    assert narration_events[0]["text"] == "Building..."
    assert narration_events[1]["text"] == "Done."

    assert len(result_events) == 1
    assert result_events[0]["data"]["success"] is True
    assert result_events[0]["data"]["artifact_id"] == "ami-sse-001"
    assert result_events[0]["data"]["grade"] == "A"


@pytest.mark.anyio
async def test_agent_build_sse_streams_error_on_exception(client):
    """When run_build_agent raises, the stream emits an error event (no 500)."""

    async def failing_agent(blueprint_yaml, provider, on_token):
        raise RuntimeError("LLM quota exceeded")

    with patch("bakex.api.agent.provider_status", return_value={"available": True, "message": "ok"}):
        with patch("bakex.api.agent.run_build_agent", side_effect=failing_agent):
            resp = client.post(
                "/api/agent/build",
                json={"blueprint_yaml": _VALID_YAML, "provider": "aws"},
            )

    assert resp.status_code == 200  # HTTP level stays 200; error is in the stream
    events = _parse_sse_events(resp.content)
    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 1
    assert "LLM quota exceeded" in error_events[0]["message"]


def test_agent_status_returns_provider_info(client):
    """GET /api/agent/status returns provider_status dict."""
    with patch(
        "bakex.api.agent.provider_status", return_value={"available": True, "provider": "anthropic", "message": "ok"}
    ):
        resp = client.get("/api/agent/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert data["provider"] == "anthropic"
