# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""StratumBuildAgent — agentic AI build system with pluggable LLM backends.

The agent accepts a blueprint YAML + provider name + credentials, then
autonomously:
  1. Validates and enriches the blueprint
  2. Triggers a build
  3. Monitors progress to completion
  4. Analyses the OSCAP compliance report
  5. Auto-retries (up to MAX_RETRIES) if the compliance grade is below B

Narration tokens stream back to the caller via an ``on_token`` async callback,
which the SSE endpoint pipes to the browser in real time.

LLM backend is selected by STRATUM_LLM_PROVIDER env var:
  anthropic (default) | openai | ollama | bedrock
See stratum/core/llm/factory.py for full env-var reference.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
BUILD_POLL_INTERVAL = 20  # seconds between build status polls
BUILD_MAX_POLLS = 180  # 60 minutes total (180 × 20 s)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    success: bool
    artifact_id: str = ""
    grade: str = ""
    score_pct: float | None = None
    summary: str = ""
    error: str = ""
    retries_used: int = 0
    final_blueprint_yaml: str = ""
    job_id: str = ""


# ---------------------------------------------------------------------------
# Tool implementations — call into Stratum's internal services directly
# ---------------------------------------------------------------------------


def _apply_required_defaults(raw: dict) -> dict:
    """Add stratum_version and kind defaults if missing — they have no schema default."""
    raw.setdefault("stratum_version", "1")
    raw.setdefault("kind", "HardeningBlueprint")
    return raw


def _validate_blueprint(yaml_text: str) -> dict:
    """Parse and validate a blueprint YAML string against the ComplianceProfile schema."""
    from stratum.core.blueprint import ComplianceProfile

    try:
        raw = yaml.safe_load(yaml_text)
        if not isinstance(raw, dict):
            return {"valid": False, "error": "Top-level document is not a YAML mapping"}
        _apply_required_defaults(raw)
        profile = ComplianceProfile.model_validate(raw)
        return {
            "valid": True,
            "profile_name": profile.metadata.name,
            "os": profile.target.os,
            "provider": profile.target.provider,
            "benchmark": profile.compliance.benchmark,
            "tier": profile.hardening.profile_tier,
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


def _enrich_blueprint(yaml_text: str, provider: str) -> dict:
    """Fill in missing or placeholder blueprint fields.

    Sets sensible defaults for base_image, instance_type, and compliance
    datastream path if they are absent or set to 'auto'.
    Returns the enriched YAML string and a list of changes made.
    """
    from stratum.core.blueprint import ComplianceProfile

    try:
        raw: dict = yaml.safe_load(yaml_text) or {}
    except Exception as exc:
        return {"error": f"YAML parse error: {exc}"}

    changes: list[str] = []
    _apply_required_defaults(raw)
    target = raw.setdefault("target", {})
    compliance = raw.setdefault("compliance", {})
    hardening = raw.setdefault("hardening", {})

    # Default provider
    if not target.get("provider") or target["provider"] == "auto":
        target["provider"] = provider
        changes.append(f"Set provider to '{provider}'")

    # Default instance type
    os_key = target.get("os", "")
    if not target.get("instance_type") or target["instance_type"] == "auto":
        instance_map = {
            "aws": "t3.medium",
            "gcp": "n2-standard-2",
            "azure": "Standard_D2s_v3",
            "digitalocean": "s-2vcpu-2gb",
            "linode": "g6-standard-2",
            "proxmox": "2cpu-4gb",
        }
        target["instance_type"] = instance_map.get(provider, "t3.medium")
        changes.append(f"Set instance_type to '{target['instance_type']}'")

    # Default root volume
    if not target.get("root_volume_size_gb"):
        target["root_volume_size_gb"] = 20
        changes.append("Set root_volume_size_gb to 20")

    # Default compliance datastream path by OS
    if not compliance.get("datastream") or compliance["datastream"] in ("auto", ""):
        _ds_map = {
            "rhel9": "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml",
            "rhel8": "/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml",
            "rocky9": "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml",
            "alma9": "/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml",
            "rocky8": "/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml",
            "alma8": "/usr/share/xml/scap/ssg/content/ssg-rhel8-ds.xml",
            "ubuntu22": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2204-ds.xml",
            "ubuntu24": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml",
            "ubuntu20": "/usr/share/xml/scap/ssg/content/ssg-ubuntu2004-ds.xml",
            "amazon-linux-2023": "/usr/share/xml/scap/ssg/content/ssg-alinux2023-ds.xml",
            "amazon2023": "/usr/share/xml/scap/ssg/content/ssg-alinux2023-ds.xml",
        }
        for key, ds in _ds_map.items():
            if os_key.startswith(key):
                compliance["datastream"] = ds
                changes.append(f"Set compliance.datastream for {os_key}")
                break

    # Default hardening profile tier
    if not hardening.get("profile_tier"):
        hardening["profile_tier"] = "cis-l1"
        changes.append("Set hardening.profile_tier to 'cis-l1'")

    try:
        ComplianceProfile.model_validate(raw)
    except Exception as exc:
        return {"error": f"Enriched blueprint fails validation: {exc}", "changes": changes}

    enriched_yaml = yaml.dump(raw, default_flow_style=False, sort_keys=False)
    return {"enriched_yaml": enriched_yaml, "changes": changes}


async def _start_build(yaml_text: str, provider: str) -> dict:
    """Load the blueprint, override the provider, and trigger a build job.

    Returns the job_id or an error.
    """
    from stratum.core import builder as build_service
    from stratum.core.blueprint import ComplianceProfile

    try:
        raw = yaml.safe_load(yaml_text)
        _apply_required_defaults(raw)
        profile = ComplianceProfile.model_validate(raw)
        profile.target.provider = provider
    except Exception as exc:
        return {"error": f"Blueprint load error: {exc}"}

    job = build_service.BuildJob(
        profile_name=profile.metadata.name,
        provider_name=provider,
    )
    build_service._jobs[job.id] = job
    asyncio.create_task(build_service.run_build(profile, Path("data/builds")))
    return {"job_id": job.id, "status": "pending"}


async def _get_build_status(job_id: str) -> dict:
    """Return the current status, last 10 log lines, and artifact_id if done."""
    from stratum.core import builder as build_service

    job = build_service.get_job(job_id)
    if job is None:
        return {"error": f"Job '{job_id}' not found"}
    return {
        "job_id": job_id,
        "status": job.status.value,
        "done": job.status in (build_service.BuildStatus.COMPLETE, build_service.BuildStatus.FAILED),
        "artifact_id": job.result.artifact_id if job.result else None,
        "error": job.error,
        "log_tail": job.log[-10:] if job.log else [],
    }


async def _get_scan_report(job_id: str) -> dict:
    """Retrieve the build job result and run an image scan to get a compliance report.

    For jobs that already have audit results attached, returns those directly.
    Otherwise, returns the artifact_id for the agent to decide next steps.
    """
    from stratum.core import builder as build_service

    build_job = build_service.get_job(job_id)
    if build_job is None:
        return {"error": f"Build job '{job_id}' not found"}
    if build_job.status.value != "complete":
        return {"error": f"Build job is not complete (status={build_job.status.value})"}

    artifact_id = build_job.result.artifact_id if build_job.result else ""
    region = build_job.result.region if build_job.result else ""
    provider = build_job.provider_name

    return {
        "artifact_id": artifact_id,
        "provider": provider,
        "region": region,
        "message": (
            "Build complete. To get a compliance report, use the Image Scanner: "
            f"POST /api/auditor/scan-image with image_id={artifact_id}, provider={provider}, region={region}."
        ),
    }


def _analyze_findings(findings_json: str) -> dict:
    """Summarise compliance findings in plain English (no extra LLM call — parsed directly).

    findings_json: JSON string with a list of failed rule dicts.
    """
    try:
        findings = json.loads(findings_json)
    except Exception:
        return {"error": "Invalid JSON in findings_json"}

    if not isinstance(findings, list):
        return {"error": "findings_json must be a JSON array"}

    by_severity: dict[str, list[str]] = {"critical": [], "high": [], "medium": [], "low": [], "unknown": []}
    for rule in findings:
        sev = (rule.get("severity") or "unknown").lower()
        rule_id = rule.get("id", "")
        title = rule.get("title", "")
        by_severity.setdefault(sev, []).append(f"{rule_id}: {title}" if title else rule_id)

    total = sum(len(v) for v in by_severity.values())
    lines = [f"Found {total} failed rules:"]
    for sev in ("critical", "high", "medium", "low"):
        items = by_severity.get(sev, [])
        if items:
            lines.append(f"\n{sev.upper()} ({len(items)}):")
            for item in items[:10]:
                lines.append(f"  • {item}")
            if len(items) > 10:
                lines.append(f"  … and {len(items) - 10} more")

    return {"summary": "\n".join(lines), "count": total, "by_severity": {k: len(v) for k, v in by_severity.items()}}


def _retry_build_yaml(yaml_text: str, modifications: str) -> dict:
    """Apply text modifications to the blueprint YAML and return the updated YAML.

    modifications: A plain-English description of changes OR a JSON patch dict.
    The agent will typically pass the full updated YAML here when retrying.
    """
    # If modifications looks like a YAML document, just validate and return it
    try:
        raw = yaml.safe_load(modifications)
        if isinstance(raw, dict):
            from stratum.core.blueprint import ComplianceProfile

            _apply_required_defaults(raw)
            ComplianceProfile.model_validate(raw)
            return {"updated_yaml": modifications, "applied": "Replacement YAML applied and validated"}
    except Exception:
        pass

    # Otherwise return original with a note — the agent should provide full YAML
    return {
        "updated_yaml": yaml_text,
        "applied": "Could not apply modifications automatically; please provide a complete updated YAML",
    }


# ---------------------------------------------------------------------------
# Tool schemas (Anthropic format)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "validate_blueprint",
        "description": "Validate a blueprint YAML string against the Stratum ComplianceProfile schema. Returns {valid: bool, error?: str, profile_name?, os?, provider?, benchmark?, tier?}",
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml_text": {"type": "string", "description": "Full blueprint YAML document"},
            },
            "required": ["yaml_text"],
        },
    },
    {
        "name": "enrich_blueprint",
        "description": "Fill in missing or auto-filled blueprint fields with sensible defaults for the target provider. Returns {enriched_yaml: str, changes: list[str]} or {error: str}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml_text": {"type": "string", "description": "Blueprint YAML to enrich"},
                "provider": {
                    "type": "string",
                    "description": "Target cloud provider (aws/gcp/azure/digitalocean/linode/proxmox)",
                },
            },
            "required": ["yaml_text", "provider"],
        },
    },
    {
        "name": "start_build",
        "description": "Trigger an image build job from a validated blueprint YAML. Returns {job_id: str, status: str} or {error: str}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml_text": {"type": "string", "description": "Validated blueprint YAML"},
                "provider": {"type": "string", "description": "Cloud provider to build on"},
            },
            "required": ["yaml_text", "provider"],
        },
    },
    {
        "name": "get_build_status",
        "description": "Poll the status of a running build job. Returns {status, done, artifact_id?, error?, log_tail}. Poll every 30–60 seconds until done=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Build job ID from start_build"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "get_scan_report",
        "description": "Retrieve the compliance scan report for a completed build job. Returns artifact_id, provider, region, and instructions to trigger a scan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Build job ID of the completed build"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "analyze_findings",
        "description": "Summarise a list of failed OSCAP compliance rules in plain English, grouped by severity. Returns {summary, count, by_severity}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "findings_json": {
                    "type": "string",
                    "description": "JSON array of failed rule objects with id, title, severity fields",
                },
            },
            "required": ["findings_json"],
        },
    },
    {
        "name": "retry_build",
        "description": "Apply modifications to a blueprint YAML and return the updated YAML ready for a new start_build call. Pass the complete updated YAML in the modifications field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml_text": {"type": "string", "description": "Current blueprint YAML"},
                "modifications": {
                    "type": "string",
                    "description": "Complete updated YAML, or plain-English description of changes",
                },
            },
            "required": ["yaml_text", "modifications"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------


async def _execute_tool(tool_name: str, tool_input: dict) -> Any:
    if tool_name == "validate_blueprint":
        return _validate_blueprint(**tool_input)
    if tool_name == "enrich_blueprint":
        return _enrich_blueprint(**tool_input)
    if tool_name == "start_build":
        return await _start_build(**tool_input)
    if tool_name == "get_build_status":
        return await _get_build_status(**tool_input)
    if tool_name == "get_scan_report":
        return await _get_scan_report(**tool_input)
    if tool_name == "analyze_findings":
        return _analyze_findings(**tool_input)
    if tool_name == "retry_build":
        return _retry_build_yaml(**tool_input)
    return {"error": f"Unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are StratumBuildAgent, an autonomous OS hardening engineer embedded in the Stratum platform.

Your mission: given a blueprint YAML and a target cloud provider, produce a production-grade
hardened image with the highest possible CIS/STIG compliance score.

## Workflow

1. **Validate** — call validate_blueprint. If invalid, explain the errors clearly and stop.
2. **Enrich** — call enrich_blueprint to fill any missing fields. Report what you changed.
3. **Build** — call start_build with the enriched YAML. Log the job_id.
4. **Monitor** — poll get_build_status every 30–60 seconds. Narrate key milestones
   (provisioning, hardening, scanning, snapshotting). If the build fails, report the
   log tail and stop.
5. **Report** — call get_scan_report. Then call analyze_findings with the failed rules
   to produce a plain-English breakdown by severity.
6. **Auto-retry** — if grade < B and retries_remaining > 0:
   - Explain what you are changing and why (e.g. enabling stricter controls)
   - Call retry_build with the updated blueprint
   - Decrement retries_remaining and go back to step 3
7. **Summary** — produce a concise final report:
   - Image ID / artifact ID
   - Compliance grade (A–F) and score percentage
   - Top 3 critical/high findings with plain-English remediation advice
   - Recommended next steps

## Style
- Narrate every step so the user understands what you are doing and why.
- Use clear section headings (##) to separate phases.
- Be specific: quote job IDs, artifact IDs, rule IDs.
- When waiting for a build, say how long it is likely to take.
- Never hallucinate results — only report what the tools return.
"""


# ---------------------------------------------------------------------------
# Main agent entry point
# ---------------------------------------------------------------------------


async def run_build_agent(
    blueprint_yaml: str,
    provider: str,
    on_token: Callable[[str], Awaitable[None]],
) -> AgentResult:
    """Run the StratumBuildAgent agentic loop.

    Args:
        blueprint_yaml: Raw YAML string of the blueprint.
        provider:       Target cloud provider name.
        on_token:       Async callback that receives narration text chunks for SSE streaming.

    Returns:
        AgentResult with the final outcome.
    """
    from stratum.core.llm import TextBlock, ToolUseBlock, get_backend

    try:
        backend = get_backend()
    except Exception as exc:
        await on_token(f"ERROR: {exc}\n")
        return AgentResult(success=False, error=str(exc))

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Build and harden this image on provider **{provider}**.\n\n"
                f"Blueprint:\n```yaml\n{blueprint_yaml}\n```\n\n"
                f"retries_remaining: {MAX_RETRIES}"
            ),
        }
    ]

    result = AgentResult(success=False, final_blueprint_yaml=blueprint_yaml)
    retries_used = 0

    while True:
        try:
            turn = await backend.agent_turn(
                messages=messages,
                tools=TOOLS,
                system=SYSTEM_PROMPT,
                max_tokens=16000,
                on_token=on_token,
            )
        except Exception as exc:
            err = f"\n\nERROR: {exc}\n"
            await on_token(err)
            result.error = str(exc)
            return result

        # Serialise turn content back into Anthropic-format dicts for history
        assistant_content: list[dict] = []
        for block in turn.content:
            if isinstance(block, TextBlock):
                assistant_content.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
        messages.append({"role": "assistant", "content": assistant_content})

        if turn.stop_reason == "end_turn":
            for block in turn.content:
                if isinstance(block, TextBlock):
                    text = block.text
                    for line in text.splitlines():
                        if "artifact" in line.lower() and ":" in line:
                            candidate = line.split(":")[-1].strip().strip("`").strip()
                            if candidate and not candidate.startswith("http"):
                                result.artifact_id = candidate
                        if "grade" in line.lower() and ":" in line:
                            parts = line.split(":")[-1].strip().split()
                            if parts and len(parts[0]) == 1 and parts[0][0] in "ABCDF":
                                result.grade = parts[0]
                    result.summary = text
            result.success = bool(result.artifact_id)
            result.retries_used = retries_used
            return result

        if turn.stop_reason != "tool_use":
            result.error = f"Unexpected stop_reason: {turn.stop_reason}"
            return result

        # Execute all tool calls and collect results
        tool_results: list[dict] = []
        for block in turn.content:
            if not isinstance(block, ToolUseBlock):
                continue
            await on_token(f"\n\n*[Calling {block.name}...]*\n")
            try:
                tool_output = await _execute_tool(block.name, block.input)
            except Exception as exc:
                tool_output = {"error": str(exc)}

            if block.name == "start_build" and isinstance(tool_output, dict):
                if "job_id" in tool_output:
                    result.job_id = tool_output["job_id"]

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(tool_output),
                }
            )

        messages.append({"role": "user", "content": tool_results})
