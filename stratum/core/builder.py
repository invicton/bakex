# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Image build orchestration: provider → ansible → oscap → golden image."""

from __future__ import annotations

import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from stratum.core.blueprint import ComplianceProfile
from stratum.core.playbook_gen import generate_prehard_playbook
from stratum.openscap import scanner as oscap_scanner
from stratum.plugins.base_provider import ProviderResult
from stratum.plugins.registry import registry

logger = logging.getLogger(__name__)


class BuildStatus(str, Enum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    HARDENING = "hardening"
    SCANNING = "scanning"
    SNAPSHOTTING = "snapshotting"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BuildJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    profile_name: str = ""
    provider_name: str = ""
    status: BuildStatus = BuildStatus.PENDING
    instance_id: str | None = None
    result: ProviderResult | None = None
    arf_path: Path | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    log: list[str] = field(default_factory=list)
    # Build target metadata (shown on the run page)
    base_image: str = ""
    region: str = ""
    instance_type: str = ""
    subnet_id: str = ""

    def _update(self, status: BuildStatus, msg: str) -> None:
        self.status = status
        self.updated_at = datetime.now(UTC)
        self.log.append(f"[{self.updated_at.isoformat()}] {msg}")
        logger.info("Job %s → %s: %s", self.id, status.value, msg)


# In-memory job store (replace with Redis/DB for production)
_jobs: dict[str, BuildJob] = {}


def get_job(job_id: str) -> BuildJob | None:
    return _jobs.get(job_id)


def list_jobs() -> list[BuildJob]:
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


async def run_build(profile: ComplianceProfile, output_dir: Path, job: BuildJob | None = None) -> BuildJob:
    """Orchestrate a full image build pipeline asynchronously.

    Steps:
        1. Provision temporary instance via provider
        2. Run Ansible hardening
        3. Run OpenSCAP scan
        4. Snapshot to golden image
        5. Teardown temp instance
    """
    if job is None:
        job = BuildJob(
            profile_name=profile.metadata.name,
            provider_name=profile.target.provider,
        )
    _jobs[job.id] = job

    provider_cls = registry.get(profile.target.provider)
    provider = provider_cls()

    handles_full = getattr(provider_cls, "handles_full_lifecycle", False)

    try:
        if handles_full:
            # Subprocess providers manage the full pipeline internally.
            # All real work happens inside snapshot() → execute_build RPC.
            # Log a single entry so the UI shows activity before the RPC call.
            job._update(
                BuildStatus.PROVISIONING,
                f"Starting full-lifecycle build via '{provider_cls.name}' provider "
                f"(provision → harden → scan → snapshot handled by provider script)",
            )
            job.instance_id = provider.provision(profile)  # returns stub immediately

            job._update(
                BuildStatus.HARDENING, "Provider script running — provisioning, hardening & scanning in progress…"
            )
            provider.run_ansible(job.instance_id, profile)  # no-op for subprocess

            job._update(BuildStatus.SNAPSHOTTING, "Finalising golden image…")
            job.result = provider.snapshot(job.instance_id, profile)  # ← all real work here
        else:
            # Class-based providers: orchestrate each stage locally.
            job._update(BuildStatus.PROVISIONING, f"Provisioning via {profile.target.provider}")
            job.instance_id = provider.provision(profile)

            playbook_path = generate_prehard_playbook(profile)
            if playbook_path is not None:
                job._update(
                    BuildStatus.HARDENING,
                    "Applying pre-hardening system configuration (hostname, filesystem, users)",
                )
                _run_prehard_ansible(playbook_path, job.instance_id)

            job._update(BuildStatus.HARDENING, "Applying Ansible-Lockdown hardening roles")
            provider.run_ansible(job.instance_id, profile)

            job._update(BuildStatus.SCANNING, "Running OpenSCAP compliance scan")
            scan_dir = output_dir / job.id
            job.arf_path = oscap_scanner.run_scan(profile, output_dir=scan_dir)

            if profile.compliance.fail_on_findings:
                from stratum.openscap.parser import RESULT_FAIL, parse_arf

                results = parse_arf(job.arf_path)
                failures = [r for r in results["rules"] if r["result"] == RESULT_FAIL]
                if failures:
                    raise RuntimeError(
                        f"{len(failures)} compliance rule(s) failed — "
                        "set fail_on_findings: false in the profile to override"
                    )

            job._update(BuildStatus.SNAPSHOTTING, "Snapshotting golden image")
            job.result = provider.snapshot(job.instance_id, profile)

        job._update(BuildStatus.COMPLETE, f"Image ready: {job.result.artifact_id}")

    except Exception as exc:
        job.error = str(exc)
        job._update(BuildStatus.FAILED, f"Build failed: {exc}")
        logger.exception("Build job %s failed", job.id)
        import asyncio as _asyncio

        from stratum.core.notifications import fire_webhook

        _asyncio.create_task(
            fire_webhook(
                "build.failed",
                {"job_id": job.id, "profile": job.profile_name, "provider": job.provider_name, "error": job.error},
            )
        )
    else:
        import asyncio as _asyncio

        from stratum.core.notifications import fire_webhook

        _asyncio.create_task(
            fire_webhook(
                "build.complete",
                {
                    "job_id": job.id,
                    "profile": job.profile_name,
                    "provider": job.provider_name,
                    "artifact_id": job.result.artifact_id if job.result else None,
                },
            )
        )
    finally:
        if job.instance_id:
            try:
                provider.teardown(job.instance_id)
            except Exception as exc:
                logger.error("Teardown failed for %s: %s", job.instance_id, exc)

    return job


def _run_prehard_ansible(playbook_path: Path, instance_id: str) -> None:
    """Run a generated pre-hardening Ansible playbook against *instance_id* over SSH.

    Assumes ``ansible-playbook`` is on PATH and the provider has set up SSH
    access (key + inventory) as part of ``provision()``.
    """
    cmd = [
        "ansible-playbook",
        "-i",
        f"{instance_id},",
        str(playbook_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Pre-hardening playbook failed (exit {result.returncode}):\n{result.stderr}")
